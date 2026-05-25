# Chat Improvements — Token Usage, Cost, Context Fill, Timing

**Status**: Design approved 2026-05-25.
**Supersedes**: `docs/CHAT_IMPROVEMENTS.md` (scoping doc — kept for reference).

---

## 1. Goal

채팅 TUI에 LLM 사용 정보를 실시간으로 표시한다.

- **Status footer (하단)**: cumulative session 정보 — model + ctx% + ↑/↓ tokens + cost
- **Per-turn footer (각 assistant 응답 아래)**: 그 턴을 처리한 model + duration

핵심 비기능 요건: **앱을 사용하는 동안 정보가 실시간으로 갱신된다.**
- duration은 응답이 끝나기 전에도 라이브로 ticking up
- token/cost/ctx% 는 UsageUpdated 이벤트 도착 즉시 footer에 반영

## 2. Non-goals

다음은 명시적으로 이 spec의 범위 밖이다.

- per-turn token/cost 표시 (cumulative footer로 통일)
- user-configurable pricing override (settings.json 머지)
- live registry fetch / 백그라운드 refresh (snapshot만 사용)
- reasoning tokens, cache read/write pricing 처리 (schema에 자리만 둠)
- 런타임 model 스위치 시 model_meta 재로딩
- compaction을 반영한 ctx% 보정

## 3. Reference architectures (조사 결과)

두 OSS 코딩 에이전트가 같은 문제를 어떻게 푸는지 조사했다.

### opencode (sst/opencode)
- **Registry**: `models.dev/api.json` (open MIT data) 를 런타임 fetch + 5분 디스크 캐시 + 60분 백그라운드 refresh + 번들된 snapshot fallback.
- **User override**: `opencode.json`의 provider blob에 deep-merge. `model.cost.input ?? existing.cost.input ?? 0` 3단 fallback.
- **Display**: model 객체에 metadata 부착. 이벤트로 흘리지 않음. session 누적 중심.

### pi (earendil-works/pi)
- **Registry**: build time에 `scripts/generate-models.ts`가 models.dev에서 fetch → `models.generated.ts`로 commit (16k 줄). 런타임 fetch 없음.
- **User override**: `~/.pi/models.json`. 새 모델 추가 또는 built-in override.
- **Token count**: provider response의 `usage` field가 1차. fallback은 `Math.ceil(chars/4)` heuristic. tiktoken 안 씀.
- **Context %**: 마지막 assistant message의 `usage.totalTokens`를 권위적 값으로 사용. 그 이후 user input은 chars/4로 추정해 합산.
- **Display**: footer 한 줄. cumulative session totals + ctx% + model. per-message cost 없음.
- **Model vs Provider**: Provider는 transport slug. Model이 metadata 캐리어. 1 provider : N models.

### poor-code의 채택 방향
pi 패턴이 가장 적합하다. 이유:

- 이름대로 minimal 지향. opencode의 런타임 fetch 인프라는 과함.
- snapshot commit 패턴은 코드량이 작고 schema는 models.dev와 동일하게 유지 가능 — 향후 fetch 도입 시 마이그레이션 cost 0.
- Provider/Model 분리는 우리 코드베이스의 기존 1급 추상화(Provider)와 잘 맞음.

## 4. Architecture overview

```
provider/registry.py (NEW)
  - _models_snapshot.json  (committed; scripts/generate_models.py로 생성)
  - ModelMeta, ModelPricing dataclass
  - lookup(model_name) → ModelMeta  (DEFAULT_META fallback, never raises)
                  │
                  ▼ (registry 의존성 주입)
provider/protocols/openai_chat.py
  - build_body: stream_options.include_usage = True
  - parser: usage chunk → UsageEnded LLMEvent
  - Ollama native field fallback (eval_count/prompt_eval_count)
                  │
                  ▼
domain/agent.py
  - run(): start_time 기록, model lookup
  - UsageEnded → cost 계산 → UsageUpdated event emit
  - TurnEnded에 duration_sec, model 캐리
                  │
                  ▼
messages.py
  - TurnEnded(turn_id, duration_sec, model)  ← 필드 추가
  - UsageUpdated(turn_id, input, output, cost_usd)  ← 기존 그대로
                  │
                  ▼
ui/store.py
  - AppState.model_meta, last_turn_tokens, turn_started_at  (NEW)
  - TurnView.duration_sec, model, started_at  (NEW)
  - reducer: ProviderChanged → lookup, TurnStarted → started_at, TurnEnded → duration/model
                  │
                  ▼
ui/widgets/
  - chat_log.TurnBlock: 라이브 ticking duration line
  - status_footer.StatusFooter (NEW): 하단 status bar
ui/screens/chat.py
  - StatusFooter mount
```

## 5. Data models

### `provider/registry.py`

```python
@dataclass(frozen=True)
class ModelPricing:
    input_per_1m: float
    output_per_1m: float
    cache_read_per_1m: float | None = None
    cache_write_per_1m: float | None = None

@dataclass(frozen=True)
class ModelMeta:
    model_id: str
    context_size: int
    max_output: int
    pricing: ModelPricing | None  # None → local/unknown pricing (e.g. Ollama)

DEFAULT_META = ModelMeta(
    model_id="<unknown>",
    context_size=128_000,
    max_output=4096,
    pricing=None,
)

def lookup(model_name: str) -> ModelMeta:
    """Exact match first, then longest-prefix match. Never raises."""
```

Snapshot 파일: `provider/_models_snapshot.json` — `scripts/generate_models.py`가 models.dev/api.json fetch 후 필요한 sub-schema(id, limit, cost)만 추출해 작성. snapshot은 repo에 commit.

### `messages.py`

```python
@dataclass(frozen=True)
class TurnEnded(Event):
    turn_id: str
    duration_sec: float    # NEW
    model: str             # NEW

# UsageUpdated — 변경 없음 (input_tokens, output_tokens, cost_usd)
```

### `provider/events.py`

```python
@dataclass(frozen=True)
class UsageEnded(LLMEvent):  # NEW
    input_tokens: int
    output_tokens: int
```

### `ui/store.py`

```python
@dataclass(frozen=True)
class TurnView:
    # 기존 필드 유지
    started_at: float | None = None      # NEW (monotonic)
    duration_sec: float | None = None    # NEW
    model: str | None = None             # NEW

@dataclass(frozen=True)
class UsageState:
    # 기존: input_tokens, output_tokens, cost_usd (cumulative)
    pass  # 변경 없음

@dataclass(frozen=True)
class AppState:
    # 기존 필드 유지
    model_meta: ModelMeta | None = None  # NEW
    last_turn_tokens: int = 0            # NEW — ctx% 계산용
```

## 6. Provider layer

### Request body

`OpenAICompatibleChat.build_body()`에 한 줄 추가:

```python
body["stream_options"] = {"include_usage": True}
```

### Usage chunk parsing

OpenAI 표준: usage chunk는 `choices: []` 이고 `usage: {prompt_tokens, completion_tokens, total_tokens}` 필드만 있는 마지막 chunk. 기존 parser의 `if not choices: return` 분기 전에 usage 처리해야 함.

```python
def parse_chunk(self, chunk):
    usage = chunk.get("usage")
    if usage:
        yield UsageEnded(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
    # ... 이후 기존 content/tool_calls 로직 ...
```

### Ollama fallback

Ollama Cloud는 OpenAI-compat이라 `stream_options.include_usage`가 통할 가능성이 높음. 미지원으로 판명되면 같은 parser에서 native field도 함께 확인:

```python
if not usage and chunk.get("done"):
    inp = chunk.get("prompt_eval_count")
    out = chunk.get("eval_count")
    if inp is not None or out is not None:
        yield UsageEnded(input_tokens=inp or 0, output_tokens=out or 0)
```

## 7. Agent layer

```python
async def run(self, cmd, cancel):
    start = time.monotonic()
    model = self.config.model
    pricing = lookup(model).pricing

    async for llm_event in self.client.stream(...):
        match llm_event:
            case UsageEnded(input_tokens=i, output_tokens=o):
                cost = _compute_cost(pricing, i, o)
                yield UsageUpdated(
                    turn_id=tid, input_tokens=i, output_tokens=o, cost_usd=cost
                )
            # ... 기타 case ...

    yield TurnEnded(
        turn_id=tid,
        duration_sec=time.monotonic() - start,
        model=model,
    )


def _compute_cost(pricing: ModelPricing | None, inp: int, out: int) -> float:
    if pricing is None:
        return 0.0
    return (inp * pricing.input_per_1m + out * pricing.output_per_1m) / 1_000_000
```

**Duration 정의**: `agent.run()` 진입부터 `TurnEnded` emit까지. tool call 포함 전체 턴. 사용자가 체감하는 wall time과 일치.

## 8. Reducer

```python
case ProviderChanged(provider_name=p, model=m):
    meta = lookup(m) if m else None
    return replace(state, provider_name=p, model=m, model_meta=meta)

case TurnStarted(cmd_id=cid, turn_id=tid):
    # 기존 update + started_at 기록
    return replace(state, turns=_update_turn_at(
        state.turns, i,
        turn_id=tid, status="running", started_at=time.monotonic(),
    ))

case TurnEnded(turn_id=tid, duration_sec=d, model=m):
    return replace(state, ..., turns=_update_turn_at(
        state.turns, i, status="done", duration_sec=d, model=m,
    ))

case UsageUpdated(input_tokens=i, output_tokens=o, cost_usd=c):
    return replace(state,
        usage=UsageState(
            input_tokens=state.usage.input_tokens + i,
            output_tokens=state.usage.output_tokens + o,
            cost_usd=state.usage.cost_usd + c,
        ),
        last_turn_tokens=i + o,   # NEW — context fill 기준값
    )
```

**ctx% 계산 결정**: 마지막 턴의 `input + output` 합 / `context_size`. pi의 패턴 차용 — provider가 실제로 카운트한 양이라 정확하고, cumulative input이 아니라 "지금 context window가 얼마나 차 있나"를 의미.

## 9. UI rendering

### Per-turn footer — 라이브 ticking

```python
# ui/widgets/chat_log.py — TurnBlock

class TurnBlock(Widget):
    def compose(self) -> ComposeResult:
        # 기존: user message + segments
        ...
        yield Static("", classes="turn-footer", id="turn-footer")

    def on_mount(self) -> None:
        # 기존 spinner 패턴 차용 — running 동안 100ms tick
        self._timer = None
        if self._turn.status == "running":
            self._start_tick()

    def _start_tick(self) -> None:
        self._timer = self.set_interval(0.1, self._refresh_footer)
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        footer = self.query_one("#turn-footer", Static)
        footer.update(self._format_footer())

    def _format_footer(self) -> str:
        t = self._turn
        # running: model 미정 — config의 model 그대로 사용
        # done: t.model 사용 (이 턴 처리한 실제 모델)
        model = t.model or self.app.app_state.model or ""
        if t.status == "running" and t.started_at is not None:
            elapsed = time.monotonic() - t.started_at
            return f"  {model} · {elapsed:.1f}s"
        if t.status in ("done", "failed") and t.duration_sec is not None:
            return f"  {model} · {t.duration_sec:.1f}s"
        return ""

    def refresh_from(self, turn: TurnView) -> None:
        # status 전환 시 timer stop, 최종 duration 표시
        ...
```

CSS:
```css
.turn-footer { color: $text-muted; height: 1; }
```

### Status footer — reactive

```python
# ui/widgets/status_footer.py (NEW)

class StatusFooter(Static):
    def on_mount(self) -> None:
        self.add_class("status-footer")
        self.watch(self.app, "app_state", self._on_state_change)
        self._apply(self.app.app_state)

    def _on_state_change(self, state: AppState) -> None:
        self._apply(state)

    def _apply(self, state: AppState) -> None:
        self.update(self._format(state))
        pct = self._ctx_pct(state)
        self.set_class(pct is not None and pct > 90, "danger")
        self.set_class(pct is not None and 70 < pct <= 90, "warn")

    @staticmethod
    def _format(state: AppState) -> str:
        u = state.usage
        ctx = StatusFooter._ctx_str(state)
        cost = f"${u.cost_usd:.4f}"
        model = state.model or ""
        return f" ↑ {_k(u.input_tokens)}  ↓ {_k(u.output_tokens)}   {cost}   {ctx}   {model}"

    @staticmethod
    def _ctx_pct(state: AppState) -> float | None:
        meta = state.model_meta
        if meta is None or meta.context_size == 0:
            return None
        return state.last_turn_tokens / meta.context_size * 100

    @staticmethod
    def _ctx_str(state: AppState) -> str:
        pct = StatusFooter._ctx_pct(state)
        meta = state.model_meta
        if pct is None or meta is None:
            return "?/?"
        return f"{pct:.0f}%/{_k(meta.context_size)}"


def _k(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)
```

CSS:
```css
.status-footer { color: $text-muted; padding: 0 1; height: 1; }
.status-footer.warn { color: $warning; }
.status-footer.danger { color: $error; }
```

### Screen mount

```python
# ui/screens/chat.py
class ChatScreen(Screen):
    def compose(self) -> ComposeResult:
        yield ChatLog(id="chat-log")
        yield PromptBox()
        yield StatusFooter(id="status-footer")
```

## 10. Real-time update mechanics

이 spec의 핵심 비기능 요건. 갱신 경로를 명시한다.

| 정보 | 갱신 트리거 | 메커니즘 |
|---|---|---|
| Per-turn duration (running) | every ~100ms while turn active | TurnBlock 내부 `set_interval` |
| Per-turn duration (final) | TurnEnded event | reducer → TurnBlock.refresh_from → footer update |
| Per-turn model | TurnEnded event | 동상 |
| Status footer tokens/cost | UsageUpdated event | reducer → reactive AppState → StatusFooter watch |
| Status footer ctx% | UsageUpdated event | 동상 (last_turn_tokens 통해) |
| Status footer model | ProviderChanged event | 동상 |

기존 reactive 인프라(`reactive[AppState]` + `Store.subscribe`)가 token/cost/ctx%/model을 자동 전파한다. **새로 도입되는 라이브 갱신**은 per-turn duration 한 건뿐 — 기존 ToolCallEntry spinner와 동일 패턴(자체 timer)이라 추가 인프라 불필요.

## 11. Behavior matrix

| 상황 | 동작 |
|---|---|
| Unknown model | `DEFAULT_META` 적용, ctx_size=128k, cost=0 |
| Pricing=None (Ollama local) | cost=0, token 카운트는 정상 |
| Provider가 usage 안 보냄 | UsageUpdated 생략, footer는 이전 값 유지 |
| ctx% < 70% | normal 색 |
| 70% < ctx% ≤ 90% | warn 색 |
| ctx% > 90% | danger 색 |
| Turn failed 도중 | duration은 그 시점까지의 elapsed, model은 config의 model |
| Turn 캔슬 (Ctrl+C) | TurnFailed로 처리, duration은 elapsed |

## 12. Implementation order

각 task는 독립 PR 가능 단위. 1~4까지 UI 변화 없이 데이터만 흐름 — 5에서 실제 표시.

```
Task 1: provider/registry.py + snapshot
  - scripts/generate_models.py (one-shot fetch from models.dev/api.json)
  - provider/_models_snapshot.json (committed)
  - provider/registry.py: ModelMeta, ModelPricing, lookup(), DEFAULT_META

Task 2: provider/openai_chat.py — usage 파싱
  - build_body에 stream_options.include_usage = True
  - parser usage chunk 처리 + Ollama native fallback
  - provider/events.py: UsageEnded LLMEvent

Task 3: messages.py + agent.py — UsageUpdated emit + timing
  - TurnEnded에 duration_sec, model 필드
  - agent.run(): start_time, lookup, UsageEnded→UsageUpdated 변환
  - _compute_cost

Task 4: store.py reducer
  - AppState.model_meta, last_turn_tokens
  - TurnView.duration_sec, model, started_at
  - ProviderChanged/TurnStarted/TurnEnded/UsageUpdated reducer 케이스

Task 5: UI
  - chat_log.TurnBlock: 라이브 ticking footer
  - ui/widgets/status_footer.py: 신규 widget
  - ui/screens/chat.py: mount
  - ui/styles/app.tcss: 새 클래스 스타일
```

## 13. Testing

| 레이어 | 테스트 | 도구 |
|---|---|---|
| `registry.lookup()` | exact, prefix(longest), unknown→DEFAULT | pytest |
| openai_chat parser | usage chunk → UsageEnded, Ollama fallback chunk | pytest |
| HTTP streaming | usage 포함 fixture, choices=[] chunk 처리 | respx |
| agent | cost 정확도, duration 측정(monkeypatch monotonic), TurnEnded payload | pytest |
| reducer | 각 event 케이스 pure in/out | pytest |
| StatusFooter | render 텍스트, warn/danger class 토글 | textual.testing |
| TurnBlock 라이브 tick | timer 시작/정지, running→done 전환 시 final duration 표시 | textual.testing |

**필수 invariant 테스트**:

1. unknown model → cost=0, ctx%는 DEFAULT 128k 기준
2. pricing=None인 model (Ollama local) → cost=0, token 카운트 정상
3. ctx% threshold class 토글: <70%/70-90%/>90%
4. duration_sec >= 0 (monotonic 보장)

## 14. Open issues to validate during implementation

```
Q1. Ollama Cloud OpenAI-compat endpoint가 stream_options.include_usage 지원?
    → 실제 호출로 확인. 미지원이면 native field fallback 경로로.
Q2. prefix 매칭 규칙: snapshot에 prefix index 별도? exact만?
    → 추천: exact 우선, miss 시 longest-prefix 단순 매칭.
       e.g. "gpt-4o-2024-08-06" → "gpt-4o-2024-08" → "gpt-4o".
Q3. 런타임 model 스위치 시 model_meta 재로딩 — 현재 spec은 /login 시점만 처리.
    → 향후 ProviderChanged가 런타임에도 발생하면 자연스럽게 lookup 재실행됨.
       추가 작업 불필요할 가능성 높음.
Q4. snapshot 갱신 주기 — 사용자 manual? CI?
    → manual로 시작. 새 모델 필요할 때 `python scripts/generate_models.py` 실행.
```
