# HANDSOFF: CC-style Loop 구현

> 이 파일은 세션 간 컨텍스트 인계용. 다음 세션은 이 파일을 읽고 바로 구현 시작 가능.

---

## 현재 상태 (2026-05-21 기준)

**브랜치:** `feat/first-agent-loop`
**스택:** Python 3.14, Textual, uv

### 즉시 착수 가능한 작업

**Phase 1+2 spec 완료.** 다음 세션은 spec → implementation plan → 구현 순으로 진행:

- 📄 spec: [`docs/superpowers/specs/2026-05-21-cc-style-loop-context-design.md`](docs/superpowers/specs/2026-05-21-cc-style-loop-context-design.md)
- 📄 한 턴 데이터 플로 reference: [`CLAUDE.md`](CLAUDE.md) (프로젝트 루트)

다음 단계: `superpowers:writing-plans` 스킬로 spec → 단계별 plan 생성 → 구현.

### 이미 구현된 것

```
src/poor_code/
├── messages.py          ← Command/Event 컨트랙트 (변경 금지)
├── app.py               ← Textual App 브리지 (변경 최소화)
├── cli.py               ← 엔트리포인트 (auth_store 연동)
├── domain/
│   ├── agent.py         ← Agent 클래스 ✅ (MAX_ITERATIONS=8, async generator)
│   └── tool/
│       ├── base.py      ← Tool Protocol, ToolContext, ExecuteResult ✅
│       ├── registry.py  ← ToolRegistry (OpenAI schema 생성) ✅
│       └── read.py      ← ReadTool ✅
├── provider/
│   ├── events.py        ← LLMEvent union ✅
│   ├── auth.py          ← BearerAuth ✅
│   ├── framing.py       ← NdjsonFraming ✅ (SSE 아님, NDJSON)
│   ├── route.py         ← Route dataclass ✅
│   ├── client.py        ← LLMClient.stream() ✅
│   ├── protocols/
│   │   └── ollama_chat.py ← OllamaChat (Ollama native /api/chat) ✅
│   └── providers/
│       └── ollama_cloud.py ← Ollama Cloud factory ✅
├── slash/
│   ├── base.py          ← SlashCommand Protocol ✅
│   ├── registry.py      ← SlashRegistry ✅
│   └── commands/login.py ← /login 커맨드 ✅
├── infra/
│   └── auth_store.py    ← API key 디스크 저장 ✅
└── ui/                  ← Textual widgets/screens/store ✅
```

### Spec 완료 — 구현 대기 (Phase 1+2)

- 컨텍스트 파일 이름: **POORCODE.md** (CLAUDE.md 아님 — 이건 우리 프로젝트의 인메모리 reference용)
- 신규 컴포넌트: `SettingsLoader`, `ContextLoader`, `SystemPromptComposer`, `PromptBuilder`, `TurnAssembler` (façade)
- 신규 디스크 surface: `~/.poor-code/` (global), `./.poor-code/` (project)
- LLMClient/OllamaChat은 **변경 없음** — system은 `messages[0]`에 role=system 메시지로 주입
- 자세한 내용은 spec 문서 참조

### 아직 spec 없는 것 (다음 라운드)

- **Phase 3: Skills 동적 로딩** (forked Agent로 실행) — 아래 plan 스케치 참고
- **Phase 4: 툴 concurrent 실행** (현재 순차만) — 아래 plan 스케치 참고
- Permission 시스템 (canUseTool)
- MCP 통합
- Hook 시스템

### Spec 작성 중 발견된 별도 이슈 (TODO)

- **`app.py:48`의 슬래시 커맨드 호출에 try/except 없음** — 슬래시 핸들러가 raise하면 Textual worker가 조용히 죽음. Agent.run()처럼 이벤트로 변환되는 경로가 없음. Phase 1+2 범위 밖이지만 별도 이슈로 빼야 함.

---

## 다음 라운드 plan 스케치 (Phase 3, 4)

> spec 단계까지 아직 안 갔음. 구현 전에 brainstorming 한 번 더 돌릴 것.

### Phase 3: Skills 동적 로딩

**구현 위치 후보:** `src/poor_code/infra/skill_loader.py`

```python
@dataclass
class SkillDef:
    name: str
    description: str
    prompt: str
    source: Path

def discover_skills(cwd: Path) -> list[SkillDef]:
    """~/.poor-code/skills/*.md + ./.poor-code/skills/*.md 탐색"""
```

**SlashRegistry에 동적 등록** — `LoginCommand` 처럼 고정 등록이 아니라
`cli.py`에서 `discover_skills()` → `SlashRegistry`에 bulk 등록.

**SkillSlashCommand** — `SlashCommand` Protocol 구현:

```python
class SkillSlashCommand:
    """스킬을 forked Agent로 실행하는 SlashCommand."""
    def __init__(self, skill: SkillDef, agent_factory: Callable) -> None: ...
    async def execute(self, ctx: SlashContext, args: list[str]) -> None:
        # 별도 Agent 인스턴스 생성 + skill.prompt를 첫 user message로 실행
        # 결과를 부모 app의 Store에 이벤트로 주입
```

설계 시 검토할 것:
- 스킬 토큰 budget 격리 (forked Agent의 history는 부모와 분리)
- 결과를 `tool_result` 형태로 부모 history에 주입할지, 별도 이벤트 종류로 표시할지
- 번들 내장 스킬을 둘지 (파일시스템 vs 패키지 리소스)

### Phase 4: 툴 concurrent 실행

**구현 위치:** `src/poor_code/domain/agent.py` 수정

```python
def _partition_calls(calls: list[_PendingCall], registry: ToolRegistry):
    """read-only 툴(read, glob, search)은 concurrent 그룹으로 분리."""

async def _execute_concurrent(calls, turn_id, ctx) -> AsyncIterator[Event]:
    results = await asyncio.gather(*[self._execute_tool_call(t, ctx) for t in calls])
```

설계 시 검토할 것:
- `Tool` Protocol에 `is_concurrency_safe: bool` 같은 메타데이터 추가 vs 레지스트리 측 분류
- max concurrency 제한 (CC는 10)
- 이벤트 순서 보장 — concurrent 그룹 내에서도 `ToolCallStarted`/`Finished`는 어느 순서로 yield할지

---

## 참고: CC 루프 아키텍처 핵심 요약

> Phase 3/4 설계 시 참조용. Phase 1+2는 이미 spec에 반영됨.

### 1. 루프 구조 (`query.ts` → `queryLoop()`)

CC의 루프는 `while(true)` async generator state machine:

```
SAMPLE: callModel(messages, systemPrompt, tools) → 스트리밍
  ↓ stop_reason == "tool_use"
TOOLS: runTools() → partitioned execution (concurrent/serial)
  ↓ tool_result messages 수집
REPEAT: state = { messages: [...old, ...toolResults], turnCount+1 }
  ↓ stop_reason == "end_turn"
DONE
```

poor-code의 현재 Agent (`domain/agent.py`) 는 이 구조를 거의 동일하게 구현함.
차이점: CC는 read-only 툴을 최대 10개 concurrent로 실행, poor-code는 순차 실행만.

### 2. Skills 탐색 (`SkillTool.ts` + `commands.ts`)

스킬 = **forked agent** (isolated token budget의 subagent):

```
/skill-name args
  → SkillTool.execute()
    → 스킬 프롬프트를 별도 Agent 인스턴스로 실행
    → 결과를 tool_result로 부모 루프에 반환
```

스킬 파일 탐색 순서:
1. 번들 내장 스킬
2. `~/.claude/commands/*.md` (유저 글로벌)
3. `./.claude/commands/*.md` (프로젝트 로컬)

파일 포맷: 마크다운 — YAML frontmatter(name, description) + 프롬프트 본문.

### 3. 툴 실행 전략 (`toolOrchestration.ts`)

```python
partitionToolCalls(blocks) → [
  { isConcurrencySafe: True,  blocks: [read, glob, ...] },  # concurrent (max 10)
  { isConcurrencySafe: False, blocks: [write, bash, ...] }, # serial
]
```

---

## 주의사항 (잊지 말 것)

1. **messages.py 변경 금지** — `ToolCallStarted`, `ToolCallFinished`, `ToolCallFailed` 이름이 UI store reducer에 하드와이어됨.
2. **domain/ → ui/ import 금지** — 단방향 의존 규칙 유지.
3. **Agent.run() 시그니처 유지** — `async def run(self, cmd, cancel) -> AsyncIterator[Event]` — UI test가 이 시그니처에 의존.
4. **OllamaChat은 `/api/chat` (native), OpenAIChat은 `/v1/chat/completions`** — 현재 provider는 Ollama native를 씀. 새 provider 추가 시 헷갈리지 말 것.
5. **framing은 NdjsonFraming** — SSE(`data: {...}\n\n`)가 아니라 NDJSON(`{...}\n`). CC 소스와 다름.
6. **CLAUDE.md (프로젝트 루트)는 poor-code agent의 메모리 reference**, POORCODE.md는 사용자가 만드는 컨텍스트 파일. 헷갈리지 말 것.
7. **에러 처리 패턴:** 표준 예외를 던지고 Agent.run()의 try/except가 도메인 이벤트(TurnFailed/ToolCallFailed)로 번역. 새 base class나 중앙 핸들러 추가하지 말 것.

---

## 관련 파일 위치

| 파일 | 역할 |
|---|---|
| `docs/superpowers/specs/2026-05-21-cc-style-loop-context-design.md` | **Phase 1+2 spec (구현 대기)** |
| `CLAUDE.md` | 한 턴 데이터 플로 + 컴포넌트 책임 요약 (poor-code agent 메모리) |
| `src/poor_code/domain/agent.py` | Agent 루프 본체 |
| `src/poor_code/provider/client.py` | LLMClient.stream() |
| `src/poor_code/slash/base.py` | SlashCommand Protocol |
| `src/poor_code/cli.py` | 엔트리포인트, 모든 것 조립 |
| `tests/provider/fakes.py` | FakeLLMClient (테스트용) |
| `docs/superpowers/specs/2026-05-20-first-agent-loop-design.md` | 기존 (초기) 설계 스펙 |
