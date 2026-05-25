# Chat Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TUI에 LLM token usage, cost, context-fill %, per-turn duration을 실시간 표시한다.

**Architecture:** pi 패턴 차용 — models.dev에서 one-shot으로 scrape한 snapshot JSON을 commit, 런타임 fetch 없음. Provider parser가 `usage` chunk를 새 `UsageEnded` LLMEvent로 변환 → Agent가 cost 계산해 `UsageUpdated` Event emit. Store reducer가 cumulative + last_turn_tokens 누적. Status footer는 reactive AppState watch, per-turn footer는 TurnBlock 자체 timer로 라이브 ticking.

**Tech Stack:** Python 3.14 · Textual 8.2+ · respx (HTTP mocking) · pytest · pytest-asyncio · Rich

**Spec reference:** `docs/superpowers/specs/2026-05-25-chat-improvements-design.md`

---

## File Structure

| Path | Responsibility | Created/Modified |
|---|---|---|
| `scripts/generate_models.py` | One-shot fetcher: models.dev/api.json → `_models_snapshot.json` | Create |
| `src/poor_code/provider/_models_snapshot.json` | Committed snapshot — id/context/output/pricing per model | Create (via script) |
| `src/poor_code/provider/registry.py` | `ModelMeta`, `ModelPricing`, `lookup()`, `DEFAULT_META` | Create |
| `src/poor_code/provider/events.py` | Add `UsageEnded` LLMEvent | Modify |
| `src/poor_code/provider/protocols/openai_chat.py` | `stream_options.include_usage`, usage chunk 파싱, Ollama fallback | Modify |
| `src/poor_code/messages.py` | `TurnEnded`에 `duration_sec`, `model` 필드 | Modify |
| `src/poor_code/domain/agent.py` | `run()`에서 start_time, cost 계산, UsageUpdated emit, TurnEnded payload | Modify |
| `src/poor_code/ui/store.py` | `TurnView`/`AppState` 필드 확장, reducer 케이스 변경 | Modify |
| `src/poor_code/ui/widgets/chat_log.py` | `TurnBlock`에 라이브 ticking footer 추가 | Modify |
| `src/poor_code/ui/widgets/status_footer.py` | 하단 status bar widget | Create |
| `src/poor_code/ui/screens/chat.py` | `StatusFooter` mount | Modify |
| `src/poor_code/ui/styles/app.tcss` | `.turn-footer`, `.status-footer`, `.warn`, `.danger` 추가 | Modify |
| `tests/provider/test_registry.py` | Registry unit tests | Create |
| `tests/provider/test_openai_chat.py` | usage chunk 파싱 테스트 추가 | Modify |
| `tests/domain/test_agent.py` (or 신규) | cost/duration/TurnEnded payload 테스트 | Create/Modify |
| `tests/ui/test_store.py` | 새 reducer 케이스 테스트 | Modify |
| `tests/ui/test_status_footer.py` | StatusFooter render 테스트 | Create |
| `tests/ui/test_chat_log.py` | TurnBlock footer ticking 테스트 추가 | Modify |

---

## Task 1: Model Registry & Snapshot

**Files:**
- Create: `scripts/generate_models.py`
- Create: `src/poor_code/provider/_models_snapshot.json` (via script)
- Create: `src/poor_code/provider/registry.py`
- Create: `tests/provider/test_registry.py`

### 1.1 Generate snapshot script

- [ ] **Step 1: Verify scripts/ directory does not exist or check what's there**

Run: `ls /Users/goddessana/Developments/poor-code/scripts/ 2>&1 || echo "directory does not exist"`
Expected: directory does not exist, OR existing scripts that we won't conflict with.

If missing: `mkdir -p /Users/goddessana/Developments/poor-code/scripts/`

- [ ] **Step 2: Write the generator script**

Create `scripts/generate_models.py`:

```python
"""One-shot fetcher: pulls models.dev/api.json and writes a minimal snapshot
into src/poor_code/provider/_models_snapshot.json.

Run manually when adding support for new models:
    python scripts/generate_models.py

We extract only the fields poor-code uses:
    id, limit.context, limit.output, cost.input, cost.output,
    cost.cache_read, cost.cache_write

models.dev returns: {<provider_id>: {models: {<model_id>: {...}}}}
We flatten to: {<model_id>: ModelMeta-like dict}, keyed by model id.
Provider attribution is dropped because lookup() in registry.py is
model-name-only — provider switching doesn't change context/pricing
for a given model id.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

URL = "https://models.dev/api.json"
OUT = Path(__file__).parent.parent / "src" / "poor_code" / "provider" / "_models_snapshot.json"


def fetch() -> dict:
    with urllib.request.urlopen(URL, timeout=30) as resp:
        return json.loads(resp.read())


def flatten(data: dict) -> dict:
    out: dict[str, dict] = {}
    for provider in data.values():
        models = provider.get("models") or {}
        for model_id, m in models.items():
            limit = m.get("limit") or {}
            cost = m.get("cost") or {}
            entry: dict = {
                "context_size": limit.get("context", 0),
                "max_output": limit.get("output", 0),
            }
            if cost:
                entry["pricing"] = {
                    "input_per_1m": cost.get("input", 0),
                    "output_per_1m": cost.get("output", 0),
                    "cache_read_per_1m": cost.get("cache_read"),
                    "cache_write_per_1m": cost.get("cache_write"),
                }
            out[model_id] = entry
    return out


def main() -> None:
    data = fetch()
    flat = flatten(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(flat, indent=2, sort_keys=True))
    print(f"Wrote {len(flat)} model entries to {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the script to produce the snapshot**

Run: `python scripts/generate_models.py`
Expected: stdout `Wrote NNN model entries to .../src/poor_code/provider/_models_snapshot.json`. File exists.

Verify with: `head -30 src/poor_code/provider/_models_snapshot.json`

Expected: well-formed JSON with model entries like:
```json
{
  "claude-3-5-sonnet-20241022": {
    "context_size": 200000,
    "max_output": 8192,
    "pricing": {
      "input_per_1m": 3.0,
      "output_per_1m": 15.0,
      ...
    }
  },
  ...
}
```

### 1.2 Registry dataclasses

- [ ] **Step 4: Write failing test for ModelMeta + ModelPricing dataclasses**

Create `tests/provider/test_registry.py`:

```python
from poor_code.provider.registry import (
    DEFAULT_META,
    ModelMeta,
    ModelPricing,
    lookup,
)


def test_model_pricing_required_fields():
    p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
    assert p.input_per_1m == 3.0
    assert p.output_per_1m == 15.0
    assert p.cache_read_per_1m is None
    assert p.cache_write_per_1m is None


def test_model_meta_with_pricing():
    p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
    m = ModelMeta(
        model_id="claude-3-5-sonnet-20241022",
        context_size=200_000,
        max_output=8192,
        pricing=p,
    )
    assert m.model_id == "claude-3-5-sonnet-20241022"
    assert m.pricing is p


def test_model_meta_pricing_optional():
    m = ModelMeta(model_id="gpt-oss-120b", context_size=128_000, max_output=4096)
    assert m.pricing is None


def test_default_meta_shape():
    assert DEFAULT_META.context_size == 128_000
    assert DEFAULT_META.max_output == 4096
    assert DEFAULT_META.pricing is None
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/provider/test_registry.py -v`
Expected: FAIL with `ImportError: No module named 'poor_code.provider.registry'`.

- [ ] **Step 6: Implement dataclasses (no lookup yet)**

Create `src/poor_code/provider/registry.py`:

```python
"""Model metadata registry. Read-only lookup keyed by model name.

The snapshot file `_models_snapshot.json` is generated by
`scripts/generate_models.py` from models.dev and committed to the repo.
No runtime fetch — regenerate the snapshot when adding new models.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


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
    pricing: ModelPricing | None = None


DEFAULT_META = ModelMeta(
    model_id="<unknown>",
    context_size=128_000,
    max_output=4096,
    pricing=None,
)


def lookup(model_name: str) -> ModelMeta:
    raise NotImplementedError  # Task 1.3
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/provider/test_registry.py -v -k "not lookup"`
Expected: 4 PASSED.

### 1.3 Lookup function — exact match

- [ ] **Step 8: Write failing test for exact-match lookup**

Append to `tests/provider/test_registry.py`:

```python
def test_lookup_exact_match():
    # Use a stable model id that should exist in any reasonable snapshot.
    # We don't assert specific numeric fields — those drift with models.dev.
    m = lookup("claude-3-5-sonnet-20241022")
    assert m.model_id == "claude-3-5-sonnet-20241022"
    assert m.context_size > 0
    assert m.pricing is not None
```

- [ ] **Step 9: Run test to verify it fails**

Run: `pytest tests/provider/test_registry.py::test_lookup_exact_match -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 10: Implement snapshot loading + exact-match lookup**

Replace `lookup()` in `src/poor_code/provider/registry.py`:

```python
_SNAPSHOT_PATH = Path(__file__).parent / "_models_snapshot.json"


def _load_snapshot() -> dict[str, dict]:
    if not _SNAPSHOT_PATH.exists():
        return {}
    return json.loads(_SNAPSHOT_PATH.read_text())


# Loaded once at import time. Snapshot is committed and never mutates.
_SNAPSHOT: dict[str, dict] = _load_snapshot()


def _build_meta(model_id: str, entry: dict) -> ModelMeta:
    pricing_dict = entry.get("pricing")
    pricing = (
        ModelPricing(
            input_per_1m=pricing_dict.get("input_per_1m", 0.0),
            output_per_1m=pricing_dict.get("output_per_1m", 0.0),
            cache_read_per_1m=pricing_dict.get("cache_read_per_1m"),
            cache_write_per_1m=pricing_dict.get("cache_write_per_1m"),
        )
        if pricing_dict
        else None
    )
    return ModelMeta(
        model_id=model_id,
        context_size=entry.get("context_size", 0) or DEFAULT_META.context_size,
        max_output=entry.get("max_output", 0) or DEFAULT_META.max_output,
        pricing=pricing,
    )


def lookup(model_name: str) -> ModelMeta:
    """Exact-match lookup against the committed snapshot.
    Returns DEFAULT_META if no match. Never raises."""
    entry = _SNAPSHOT.get(model_name)
    if entry is not None:
        return _build_meta(model_name, entry)
    return DEFAULT_META
```

- [ ] **Step 11: Run tests to verify exact match passes**

Run: `pytest tests/provider/test_registry.py -v`
Expected: 5 PASSED.

### 1.4 Lookup — longest-prefix fallback

- [ ] **Step 12: Write failing test for longest-prefix match**

Append to `tests/provider/test_registry.py`:

```python
def test_lookup_longest_prefix_match():
    # A versioned model id that won't appear in models.dev verbatim
    # but whose base name does. Pick a real base like "gpt-4o".
    base = lookup("gpt-4o")
    assert base.model_id == "gpt-4o"  # sanity — base exists

    # Hypothetical date-suffixed variant — should fall back to "gpt-4o".
    versioned = lookup("gpt-4o-2099-12-31")
    assert versioned.model_id == "gpt-4o"
    assert versioned.context_size == base.context_size


def test_lookup_unknown_returns_default():
    m = lookup("this-model-definitely-does-not-exist-xyz")
    assert m is DEFAULT_META
```

- [ ] **Step 13: Run tests to verify the prefix one fails**

Run: `pytest tests/provider/test_registry.py::test_lookup_longest_prefix_match tests/provider/test_registry.py::test_lookup_unknown_returns_default -v`
Expected: `test_lookup_longest_prefix_match` FAIL (returns DEFAULT_META instead of base); `test_lookup_unknown_returns_default` PASS.

- [ ] **Step 14: Extend `lookup()` with longest-prefix fallback**

Replace the body of `lookup()` in `src/poor_code/provider/registry.py`:

```python
def lookup(model_name: str) -> ModelMeta:
    """Exact match first, then longest-prefix match against snapshot keys.
    Returns DEFAULT_META if nothing matches. Never raises."""
    entry = _SNAPSHOT.get(model_name)
    if entry is not None:
        return _build_meta(model_name, entry)

    # Longest-prefix: find the snapshot key that is the longest prefix of
    # model_name. Example: "gpt-4o-2099-12-31" → "gpt-4o" if present.
    best_key: str | None = None
    for key in _SNAPSHOT:
        if model_name.startswith(key) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    if best_key is not None:
        return _build_meta(best_key, _SNAPSHOT[best_key])

    return DEFAULT_META
```

- [ ] **Step 15: Run all registry tests to verify pass**

Run: `pytest tests/provider/test_registry.py -v`
Expected: 7 PASSED.

### 1.5 Commit

- [ ] **Step 16: Commit Task 1**

```bash
git add -f docs/superpowers/specs/2026-05-25-chat-improvements-design.md \
            docs/superpowers/plans/2026-05-25-chat-improvements.md
git add scripts/generate_models.py \
        src/poor_code/provider/registry.py \
        src/poor_code/provider/_models_snapshot.json \
        tests/provider/test_registry.py
git commit -m "feat(provider): add model registry with models.dev snapshot"
```

Note: `docs/` is in `.gitignore` — use `-f` for the spec/plan files.

---

## Task 2: Usage Parsing in OpenAI Protocol

**Files:**
- Modify: `src/poor_code/provider/events.py`
- Modify: `src/poor_code/provider/protocols/openai_chat.py`
- Modify: `tests/provider/test_openai_chat.py`

### 2.1 New LLMEvent: UsageEnded

- [ ] **Step 1: Write failing test for UsageEnded import**

Append to `tests/provider/test_openai_chat.py`:

```python
from poor_code.provider.events import UsageEnded


def test_usage_ended_dataclass_fields():
    u = UsageEnded(input_tokens=120, output_tokens=45)
    assert u.input_tokens == 120
    assert u.output_tokens == 45
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/provider/test_openai_chat.py::test_usage_ended_dataclass_fields -v`
Expected: FAIL with `ImportError: cannot import name 'UsageEnded'`.

- [ ] **Step 3: Add `UsageEnded` to events module**

Modify `src/poor_code/provider/events.py` — append at end:

```python
@dataclass(frozen=True)
class UsageEnded(LLMEvent):
    """Provider's reported token counts for the completed stream.
    Pricing/cost is computed by the Agent layer, not here."""
    input_tokens: int
    output_tokens: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/provider/test_openai_chat.py::test_usage_ended_dataclass_fields -v`
Expected: PASS.

### 2.2 Request body — stream_options.include_usage

- [ ] **Step 5: Write failing test for stream_options in build_body**

Append to `tests/provider/test_openai_chat.py`:

```python
def test_build_body_sets_include_usage():
    body = OpenAICompatibleChat().build_body(messages=[], tools=[], model="m")
    assert body.get("stream_options") == {"include_usage": True}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/provider/test_openai_chat.py::test_build_body_sets_include_usage -v`
Expected: FAIL — `stream_options` missing from body.

- [ ] **Step 7: Add `stream_options` to `build_body`**

In `src/poor_code/provider/protocols/openai_chat.py`, modify `build_body()`:

```python
def build_body(
    self,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        body["tools"] = tools
    return body
```

- [ ] **Step 8: Run all openai_chat tests to verify no regressions**

Run: `pytest tests/provider/test_openai_chat.py -v`
Expected: all existing tests still PASS + the new one PASSes.

### 2.3 Parse usage chunk → UsageEnded

- [ ] **Step 9: Write failing test for usage chunk parsing**

Append to `tests/provider/test_openai_chat.py`:

```python
def test_parse_usage_chunk_emits_usage_ended():
    """OpenAI's final usage chunk: choices=[] and usage payload."""
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "choices": [],
        "usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
    }))
    assert UsageEnded(input_tokens=120, output_tokens=45) in events


def test_parse_usage_chunk_with_content_chunk_does_not_break():
    """Standard content chunks have no `usage` field — still parsed."""
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "choices": [{"delta": {"content": "hi"}, "finish_reason": None}]
    }))
    assert events == [TextDelta(text="hi")]


def test_parse_usage_chunk_zero_tokens_still_emits():
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "choices": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }))
    assert UsageEnded(input_tokens=0, output_tokens=0) in events
```

- [ ] **Step 10: Run test to verify the new ones fail**

Run: `pytest tests/provider/test_openai_chat.py::test_parse_usage_chunk_emits_usage_ended -v`
Expected: FAIL — parser returns no events (currently bails on `if not choices`).

- [ ] **Step 11: Modify parser to handle usage chunks before choices guard**

Edit `src/poor_code/provider/protocols/openai_chat.py` — replace the body of `_OpenAIChatParser.parse_chunk` so usage is handled first:

```python
def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
    # OpenAI's final-chunk usage frame has choices=[] (or absent) and
    # usage populated. Emit UsageEnded before bailing on no-choices.
    usage = chunk.get("usage")
    if usage:
        yield UsageEnded(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    choices = chunk.get("choices") or []
    if not choices:
        return

    choice = choices[0]
    delta = choice.get("delta") or {}
    finish_reason = choice.get("finish_reason")

    content = delta.get("content")
    if content:
        yield TextDelta(text=content)

    for tc in delta.get("tool_calls") or []:
        idx = tc.get("index", 0)
        if idx not in self._calls:
            self._calls[idx] = {"id": tc.get("id") or "", "name": "", "args": ""}
        call = self._calls[idx]
        fn = tc.get("function") or {}
        if fn.get("name"):
            call["name"] = fn["name"]
        if fn.get("arguments"):
            call["args"] += fn["arguments"]

    if finish_reason is not None:
        for idx in sorted(self._calls):
            call = self._calls[idx]
            call_id = call["id"] or uuid.uuid4().hex
            yield ToolCallStarted(call_id=call_id, name=call["name"])
            yield ToolCallInputDelta(call_id=call_id, json_delta=call["args"] or "{}")
            yield ToolCallEnded(call_id=call_id)
        reason = finish_reason if finish_reason in _VALID_REASONS else "stop"
        yield FinishedReason(reason=reason)
```

Add `UsageEnded` to the import at the top of the file:

```python
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
    UsageEnded,
)
```

- [ ] **Step 12: Run all openai_chat tests to verify pass**

Run: `pytest tests/provider/test_openai_chat.py -v`
Expected: all PASS (including the three new usage tests).

### 2.4 Ollama native-field fallback

- [ ] **Step 13: Write failing test for Ollama-shaped final chunk**

Append to `tests/provider/test_openai_chat.py`:

```python
def test_parse_ollama_final_chunk_falls_back_to_eval_count():
    """Ollama's native /api/chat done chunk uses prompt_eval_count/eval_count
    instead of OpenAI's usage. When `usage` is absent but `done=true` and
    the eval counts are present, emit UsageEnded from those."""
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "done": True,
        "prompt_eval_count": 80,
        "eval_count": 30,
    }))
    assert UsageEnded(input_tokens=80, output_tokens=30) in events


def test_parse_ollama_fallback_not_triggered_when_usage_present():
    """If both `usage` and Ollama fields exist, OpenAI usage wins."""
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "done": True,
        "prompt_eval_count": 80,
        "eval_count": 30,
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }))
    usage_events = [e for e in events if isinstance(e, UsageEnded)]
    assert usage_events == [UsageEnded(input_tokens=100, output_tokens=50)]
```

- [ ] **Step 14: Run tests to verify they fail**

Run: `pytest tests/provider/test_openai_chat.py::test_parse_ollama_final_chunk_falls_back_to_eval_count tests/provider/test_openai_chat.py::test_parse_ollama_fallback_not_triggered_when_usage_present -v`
Expected: first FAIL (no UsageEnded emitted), second PASS (no Ollama fields read).

- [ ] **Step 15: Add Ollama fallback to parser**

In `_OpenAIChatParser.parse_chunk`, after the `usage` block, before the `choices` guard:

```python
def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
    usage = chunk.get("usage")
    if usage:
        yield UsageEnded(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
    elif chunk.get("done") and (
        chunk.get("prompt_eval_count") is not None
        or chunk.get("eval_count") is not None
    ):
        # Ollama native shape — no OpenAI `usage` field; fall back to its
        # own eval counts. Only triggers when the OpenAI shape is absent.
        yield UsageEnded(
            input_tokens=chunk.get("prompt_eval_count") or 0,
            output_tokens=chunk.get("eval_count") or 0,
        )

    # ... rest unchanged ...
```

- [ ] **Step 16: Run all openai_chat tests**

Run: `pytest tests/provider/test_openai_chat.py -v`
Expected: all PASS.

### 2.5 Commit Task 2

- [ ] **Step 17: Commit**

```bash
git add src/poor_code/provider/events.py \
        src/poor_code/provider/protocols/openai_chat.py \
        tests/provider/test_openai_chat.py
git commit -m "feat(provider): parse usage chunks into UsageEnded LLMEvent"
```

---

## Task 3: Agent Layer — TurnEnded payload, cost calculation, UsageUpdated emit

**Files:**
- Modify: `src/poor_code/messages.py`
- Modify: `src/poor_code/domain/agent.py`
- Create or Modify: `tests/domain/test_agent.py`

### 3.1 Extend TurnEnded with duration_sec + model

- [ ] **Step 1: Verify which tests reference TurnEnded so we know what may break**

Run: `grep -rn "TurnEnded(" /Users/goddessana/Developments/poor-code/tests/ /Users/goddessana/Developments/poor-code/src/poor_code/`
Expected: a list of construction sites. Each will need to pass `duration_sec` and `model` after Step 3.

- [ ] **Step 2: Write failing test for TurnEnded with new fields**

If `tests/domain/test_agent.py` does not exist, create it. Otherwise, append:

```python
from poor_code.messages import TurnEnded


def test_turn_ended_carries_duration_and_model():
    e = TurnEnded(turn_id="t1", duration_sec=1.25, model="gpt-4o")
    assert e.turn_id == "t1"
    assert e.duration_sec == 1.25
    assert e.model == "gpt-4o"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/domain/test_agent.py::test_turn_ended_carries_duration_and_model -v`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'duration_sec'`.

- [ ] **Step 4: Add `duration_sec` and `model` to TurnEnded**

In `src/poor_code/messages.py`, replace `TurnEnded`:

```python
@dataclass(frozen=True)
class TurnEnded(Event):
    turn_id: str
    duration_sec: float
    model: str
```

- [ ] **Step 5: Update all in-repo `TurnEnded(...)` construction sites**

Concretely there are 7 construction sites in this repo (2 src + 5 tests). Update each one:

**src** — `src/poor_code/domain/agent.py:140` and `:154`. Both currently read `yield TurnEnded(turn_id=turn_id)`. Change both to:

```python
yield TurnEnded(turn_id=turn_id, duration_sec=0.0, model="")
```

(These are placeholders that Task 3.3 replaces with real values. Keeping the build green between tasks.)

**tests** — update these to add the new args. The exact replacement is `TurnEnded(turn_id="...")` → `TurnEnded(turn_id="...", duration_sec=0.0, model="")`:

- `tests/ui/test_prompt_box.py:239` — `TurnEnded(turn_id="t1")`
- `tests/ui/test_prompt_box.py:261` — `TurnEnded(turn_id="t1")`
- `tests/ui/test_store.py:83` — `TurnEnded(turn_id="T1")`
- `tests/test_messages.py:91` — `TurnEnded(turn_id="t")`

(Note: `src/poor_code/ui/store.py:208` uses a pattern match `case TurnEnded(turn_id=tid):` — this is NOT a construction. Leave it alone for now; Task 4.4 replaces this case statement with the new shape.)

- [ ] **Step 6: Run the full suite to confirm nothing else broke**

Run: `pytest -x`
Expected: PASS. If anything still references `TurnEnded(turn_id=...)` without the new args, the trace shows the line — add the placeholder args.

### 3.2 cost computation helper

- [ ] **Step 7: Write failing test for cost computation**

Append to `tests/domain/test_agent.py`:

```python
from poor_code.domain.agent import _compute_cost
from poor_code.provider.registry import ModelPricing


def test_compute_cost_with_pricing():
    p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
    # 1000 input @ $3/M + 500 output @ $15/M = 0.003 + 0.0075 = 0.0105
    cost = _compute_cost(p, 1000, 500)
    assert cost == pytest.approx(0.0105)


def test_compute_cost_none_pricing_returns_zero():
    assert _compute_cost(None, 1000, 500) == 0.0


def test_compute_cost_zero_tokens():
    p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
    assert _compute_cost(p, 0, 0) == 0.0
```

Make sure `import pytest` is present at top of the test file.

- [ ] **Step 8: Run to verify failure**

Run: `pytest tests/domain/test_agent.py::test_compute_cost_with_pricing -v`
Expected: FAIL — `ImportError: cannot import name '_compute_cost'`.

- [ ] **Step 9: Add `_compute_cost` to agent.py**

In `src/poor_code/domain/agent.py`, after the top-level imports and before the `Agent` class:

```python
from poor_code.provider.registry import ModelPricing, lookup


def _compute_cost(
    pricing: ModelPricing | None,
    input_tokens: int,
    output_tokens: int,
) -> float:
    if pricing is None:
        return 0.0
    return (
        input_tokens * pricing.input_per_1m
        + output_tokens * pricing.output_per_1m
    ) / 1_000_000
```

Also extend the existing import from `poor_code.messages` to include `UsageUpdated`:

```python
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    Command,
    Event,
    RunSlashCommand,
    SendPrompt,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnded,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
)
```

And extend `provider.events` import:

```python
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted as ProviderToolCallStarted,
    UsageEnded,
)
```

- [ ] **Step 10: Run cost tests to verify pass**

Run: `pytest tests/domain/test_agent.py::test_compute_cost_with_pricing tests/domain/test_agent.py::test_compute_cost_none_pricing_returns_zero tests/domain/test_agent.py::test_compute_cost_zero_tokens -v`
Expected: 3 PASSED.

### 3.3 Agent.run — duration measurement and UsageEnded translation

This is the substantive integration. We need to:
1. Capture `start_time = time.monotonic()` at the top of `run()`.
2. Resolve the model name (from `llm.model` if available, fallback to empty).
3. Lookup pricing once per turn.
4. Inside the stream loop, translate `UsageEnded → UsageUpdated` with computed cost.
5. Emit `TurnEnded` with the real `duration_sec` and `model` (both at the early return after MAX_ITERATIONS and after the `if not call_order:` branch).

- [ ] **Step 11: Write integration test using a FakeLLMClient**

Inspect existing fakes: `tests/provider/fakes.py` likely has a `FakeLLMClient`. Run:
```
grep -n "FakeLLMClient\|class Fake" /Users/goddessana/Developments/poor-code/tests/provider/fakes.py
```

If a fake exists that streams a scripted sequence of `LLMEvent`s, use it. Otherwise, write a minimal fake inline. Append to `tests/domain/test_agent.py`:

```python
import asyncio
import pytest

from poor_code.domain.agent import Agent
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.messages import SendPrompt, UsageUpdated
from poor_code.provider.events import (
    FinishedReason,
    TextDelta,
    UsageEnded,
)


class _FakeLLM:
    """Streams a scripted list of LLMEvent values. .model lets the Agent
    resolve which model handled the turn."""
    def __init__(self, events, model: str = "gpt-4o"):
        self._events = events
        self.model = model

    async def stream(self, messages, tools):
        for ev in self._events:
            yield ev


@pytest.mark.asyncio
async def test_agent_emits_usage_updated_with_cost(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    events = [
        TextDelta(text="hello"),
        UsageEnded(input_tokens=1000, output_tokens=500),
        FinishedReason(reason="stop"),
    ]
    llm = _FakeLLM(events, model="gpt-4o")
    agent = Agent(llm=llm, tools=ToolRegistry(), assembler=TurnAssembler())
    cancel = asyncio.Event()

    out_events = []
    async for ev in agent.run(SendPrompt(text="hi"), cancel):
        out_events.append(ev)

    usage_events = [e for e in out_events if isinstance(e, UsageUpdated)]
    assert len(usage_events) == 1
    u = usage_events[0]
    assert u.input_tokens == 1000
    assert u.output_tokens == 500
    # gpt-4o pricing from models.dev snapshot is non-zero — assert positive.
    assert u.cost_usd > 0


@pytest.mark.asyncio
async def test_agent_turn_ended_carries_duration_and_model(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    events = [
        TextDelta(text="hi"),
        FinishedReason(reason="stop"),
    ]
    llm = _FakeLLM(events, model="gpt-4o")
    agent = Agent(llm=llm, tools=ToolRegistry(), assembler=TurnAssembler())
    cancel = asyncio.Event()

    from poor_code.messages import TurnEnded
    end = None
    async for ev in agent.run(SendPrompt(text="hi"), cancel):
        if isinstance(ev, TurnEnded):
            end = ev
    assert end is not None
    assert end.model == "gpt-4o"
    assert end.duration_sec >= 0.0  # monotonic guarantee
```

Note: the existing `Agent.__init__` may require specific arguments — adjust to whatever the project's conftest fixtures or existing agent tests already use. Run `grep -n "Agent(" tests/` to see the typical construction.

- [ ] **Step 12: Run the new tests to verify they fail**

Run: `pytest tests/domain/test_agent.py::test_agent_emits_usage_updated_with_cost tests/domain/test_agent.py::test_agent_turn_ended_carries_duration_and_model -v`
Expected: FAIL — `UsageUpdated` never emitted (parser case missing) and `TurnEnded.model == ""` (placeholder).

- [ ] **Step 13: Wire duration + model + UsageEnded handling into `Agent.run`**

In `src/poor_code/domain/agent.py`, modify the `run()` method. Add `import time` at top of the file if not present.

At the top of `run()` (after the existing `turn_id = uuid.uuid4().hex` line), insert:

```python
start_time = time.monotonic()
model_name = getattr(self.llm, "model", "") or ""
pricing = lookup(model_name).pricing
```

Inside the existing `match ev:` block in the `async for ev in self.llm.stream(...)` loop, add a new case before the `FinishedReason` case:

```python
case UsageEnded(input_tokens=in_tok, output_tokens=out_tok):
    yield UsageUpdated(
        turn_id=turn_id,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=_compute_cost(pricing, in_tok, out_tok),
    )
```

Replace both `yield TurnEnded(turn_id=turn_id, duration_sec=0.0, model="")` with:

```python
yield TurnEnded(
    turn_id=turn_id,
    duration_sec=time.monotonic() - start_time,
    model=model_name,
)
```

- [ ] **Step 14: Run the agent tests to verify they pass**

Run: `pytest tests/domain/test_agent.py -v`
Expected: all PASS.

- [ ] **Step 15: Run the full suite to confirm no other tests broke**

Run: `pytest -x`
Expected: PASS.

### 3.4 Commit Task 3

- [ ] **Step 16: Commit**

```bash
git add src/poor_code/messages.py \
        src/poor_code/domain/agent.py \
        tests/domain/test_agent.py
git commit -m "feat(agent): emit UsageUpdated with cost + TurnEnded with duration/model"
```

If any other tests under `tests/` had to be updated to pass the new `TurnEnded` args (from Step 5), include them in the same commit.

---

## Task 4: Store reducer extensions

**Files:**
- Modify: `src/poor_code/ui/store.py`
- Modify: `tests/ui/test_store.py`

### 4.1 New AppState + TurnView fields

- [ ] **Step 1: Write failing test for new field defaults**

Append to `tests/ui/test_store.py`:

```python
from poor_code.provider.registry import ModelMeta


def test_app_state_has_model_meta_default_none():
    s = AppState()
    assert s.model_meta is None


def test_app_state_has_last_turn_tokens_default_zero():
    s = AppState()
    assert s.last_turn_tokens == 0


def test_turn_view_has_new_fields_default_none():
    t = TurnView(turn_id=None, cmd_id="c1", user_text="hi")
    assert t.started_at is None
    assert t.duration_sec is None
    assert t.model is None
```

- [ ] **Step 2: Run tests to verify failures**

Run: `pytest tests/ui/test_store.py::test_app_state_has_model_meta_default_none tests/ui/test_store.py::test_app_state_has_last_turn_tokens_default_zero tests/ui/test_store.py::test_turn_view_has_new_fields_default_none -v`
Expected: 3 FAIL.

- [ ] **Step 3: Extend dataclasses**

In `src/poor_code/ui/store.py`, modify the existing classes.

Add import at top:
```python
from poor_code.provider.registry import ModelMeta
```

Modify `TurnView`:
```python
@dataclass(frozen=True)
class TurnView:
    turn_id: str | None
    cmd_id: str
    user_text: str
    segments: tuple[Segment, ...] = ()
    status: Literal["pending", "running", "done", "failed"] = "pending"
    error: str | None = None
    started_at: float | None = None        # monotonic, set by TurnStarted
    duration_sec: float | None = None      # set by TurnEnded
    model: str | None = None               # set by TurnEnded

    # ... existing assistant_text/tool_calls properties unchanged ...
```

Modify `AppState`:
```python
@dataclass(frozen=True)
class AppState:
    turns: tuple[TurnView, ...] = ()
    is_processing: bool = False
    usage: UsageState = field(default_factory=UsageState)
    last_error: str | None = None
    cwd: str = ""
    provider_name: str | None = None
    model: str | None = None
    model_meta: ModelMeta | None = None
    last_turn_tokens: int = 0
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/ui/test_store.py::test_app_state_has_model_meta_default_none tests/ui/test_store.py::test_app_state_has_last_turn_tokens_default_zero tests/ui/test_store.py::test_turn_view_has_new_fields_default_none -v`
Expected: 3 PASS.

### 4.2 ProviderChanged → set model_meta

- [ ] **Step 5: Write failing test**

Append to `tests/ui/test_store.py`:

```python
from poor_code.ui.store import ProviderChanged


def test_provider_changed_sets_model_meta_from_lookup():
    s = AppState()
    s2 = reduce(s, ProviderChanged(provider_name="openai", model="gpt-4o"))
    assert s2.model == "gpt-4o"
    assert s2.model_meta is not None
    assert s2.model_meta.context_size > 0


def test_provider_changed_with_none_model_clears_meta():
    s = AppState(model="gpt-4o")  # pretend previously set
    s2 = reduce(s, ProviderChanged(provider_name=None, model=None))
    assert s2.model is None
    assert s2.model_meta is None
```

- [ ] **Step 6: Run tests — first should fail (meta not set), second should pass already**

Run: `pytest tests/ui/test_store.py::test_provider_changed_sets_model_meta_from_lookup tests/ui/test_store.py::test_provider_changed_with_none_model_clears_meta -v`
Expected: first FAIL (`model_meta is None`), second PASS.

- [ ] **Step 7: Update ProviderChanged reducer case**

In `src/poor_code/ui/store.py`, change the `ProviderChanged` case. Add import at top:
```python
from poor_code.provider.registry import lookup
```

Then replace the case:
```python
case ProviderChanged(provider_name=p, model=m):
    meta = lookup(m) if m else None
    return replace(state, provider_name=p, model=m, model_meta=meta)
```

- [ ] **Step 8: Run tests to verify pass**

Run: `pytest tests/ui/test_store.py -k "provider_changed" -v`
Expected: both PASS.

### 4.3 TurnStarted → set started_at

- [ ] **Step 9: Write failing test**

Append to `tests/ui/test_store.py`:

```python
def test_turn_started_records_started_at():
    s = AppState(turns=(TurnView(turn_id=None, cmd_id="c1", user_text="hi"),))
    s2 = reduce(s, TurnStarted(cmd_id="c1", turn_id="t1"))
    assert s2.turns[0].turn_id == "t1"
    assert s2.turns[0].status == "running"
    assert s2.turns[0].started_at is not None
    assert s2.turns[0].started_at > 0  # monotonic always positive
```

- [ ] **Step 10: Run test to verify failure**

Run: `pytest tests/ui/test_store.py::test_turn_started_records_started_at -v`
Expected: FAIL — `started_at is None`.

- [ ] **Step 11: Update TurnStarted reducer case**

In `src/poor_code/ui/store.py`, add `import time` at top.

Change the `TurnStarted` case:
```python
case TurnStarted(cmd_id=cid, turn_id=tid):
    i = _find_turn_by_cmd(state, cid)
    if i is None:
        return state
    return replace(
        state,
        turns=_update_turn_at(
            state.turns, i,
            turn_id=tid,
            status="running",
            started_at=time.monotonic(),
        ),
    )
```

- [ ] **Step 12: Run test to verify pass**

Run: `pytest tests/ui/test_store.py::test_turn_started_records_started_at -v`
Expected: PASS.

### 4.4 TurnEnded → set duration_sec + model

- [ ] **Step 13: Write failing test**

Append to `tests/ui/test_store.py`:

```python
def test_turn_ended_sets_duration_and_model():
    s = AppState(turns=(
        TurnView(turn_id="t1", cmd_id="c1", user_text="hi", status="running"),
    ))
    s2 = reduce(s, TurnEnded(turn_id="t1", duration_sec=2.5, model="gpt-4o"))
    t = s2.turns[0]
    assert t.status == "done"
    assert t.duration_sec == 2.5
    assert t.model == "gpt-4o"
    assert s2.is_processing is False
```

- [ ] **Step 14: Run test to verify failure**

Run: `pytest tests/ui/test_store.py::test_turn_ended_sets_duration_and_model -v`
Expected: FAIL — `duration_sec` and `model` not set.

- [ ] **Step 15: Update TurnEnded reducer case**

In `src/poor_code/ui/store.py`, change the `TurnEnded` case:
```python
case TurnEnded(turn_id=tid, duration_sec=d, model=m):
    i = _find_turn_by_id(state, tid)
    if i is None:
        return state
    return replace(
        state,
        turns=_update_turn_at(
            state.turns, i,
            status="done",
            duration_sec=d,
            model=m,
        ),
        is_processing=False,
    )
```

- [ ] **Step 16: Run test to verify pass**

Run: `pytest tests/ui/test_store.py::test_turn_ended_sets_duration_and_model -v`
Expected: PASS.

### 4.5 UsageUpdated → cumulative + last_turn_tokens

- [ ] **Step 17: Write failing test**

Append to `tests/ui/test_store.py`:

```python
from poor_code.messages import UsageUpdated


def test_usage_updated_accumulates_and_sets_last_turn_tokens():
    s = AppState(usage=UsageState(input_tokens=100, output_tokens=50, cost_usd=0.001))
    s2 = reduce(
        s,
        UsageUpdated(turn_id="t1", input_tokens=200, output_tokens=80, cost_usd=0.005),
    )
    assert s2.usage.input_tokens == 300       # accumulated
    assert s2.usage.output_tokens == 130
    assert s2.usage.cost_usd == pytest.approx(0.006)
    assert s2.last_turn_tokens == 280         # this turn's input + output (NOT cumulative)
```

Make sure `import pytest` is in this test file.

- [ ] **Step 18: Run test to verify failure**

Run: `pytest tests/ui/test_store.py::test_usage_updated_accumulates_and_sets_last_turn_tokens -v`
Expected: FAIL — `last_turn_tokens == 0` (the new field never updated).

- [ ] **Step 19: Update UsageUpdated reducer case**

In `src/poor_code/ui/store.py`, change the `UsageUpdated` case:
```python
case UsageUpdated(input_tokens=i_in, output_tokens=i_out, cost_usd=c):
    return replace(
        state,
        usage=UsageState(
            input_tokens=state.usage.input_tokens + i_in,
            output_tokens=state.usage.output_tokens + i_out,
            cost_usd=state.usage.cost_usd + c,
        ),
        last_turn_tokens=i_in + i_out,
    )
```

- [ ] **Step 20: Run test + full store suite to verify pass**

Run: `pytest tests/ui/test_store.py -v`
Expected: all PASS.

### 4.6 Commit Task 4

- [ ] **Step 21: Commit**

```bash
git add src/poor_code/ui/store.py tests/ui/test_store.py
git commit -m "feat(store): wire model_meta, duration/model on TurnView, last_turn_tokens"
```

---

## Task 5: UI rendering — per-turn footer + StatusFooter

**Files:**
- Modify: `src/poor_code/ui/widgets/chat_log.py`
- Create: `src/poor_code/ui/widgets/status_footer.py`
- Modify: `src/poor_code/ui/screens/chat.py`
- Modify: `src/poor_code/ui/styles/app.tcss`
- Create: `tests/ui/test_status_footer.py`
- Modify: `tests/ui/test_chat_log.py`

### 5.1 StatusFooter widget — static rendering

- [ ] **Step 1: Write failing test for StatusFooter format**

Create `tests/ui/test_status_footer.py`:

```python
from poor_code.provider.registry import ModelMeta, ModelPricing
from poor_code.ui.store import AppState, UsageState
from poor_code.ui.widgets.status_footer import StatusFooter, _k


def test_k_under_1000():
    assert _k(0) == "0"
    assert _k(500) == "500"
    assert _k(999) == "999"


def test_k_over_1000():
    assert _k(1000) == "1.0k"
    assert _k(4521) == "4.5k"
    assert _k(128_000) == "128.0k"


def test_status_footer_format_with_meta_and_usage():
    meta = ModelMeta(
        model_id="gpt-4o",
        context_size=128_000,
        max_output=16384,
        pricing=ModelPricing(input_per_1m=2.5, output_per_1m=10.0),
    )
    state = AppState(
        model="gpt-4o",
        model_meta=meta,
        usage=UsageState(input_tokens=4200, output_tokens=1100, cost_usd=0.034),
        last_turn_tokens=5300,
    )
    text = StatusFooter._format(state)
    # Spot-check the major substrings — exact spacing is fragile.
    assert "4.2k" in text     # input
    assert "1.1k" in text     # output
    assert "$0.0340" in text  # 4-decimal cost
    assert "4%" in text       # 5300/128000 ≈ 4.1%
    assert "128.0k" in text   # context window
    assert "gpt-4o" in text


def test_status_footer_no_meta_renders_unknown_ctx():
    state = AppState(model=None, model_meta=None, usage=UsageState())
    text = StatusFooter._format(state)
    assert "?/?" in text


def test_ctx_pct_returns_none_when_no_meta():
    state = AppState(model_meta=None, last_turn_tokens=1000)
    assert StatusFooter._ctx_pct(state) is None


def test_ctx_pct_computes_from_last_turn_tokens():
    meta = ModelMeta(model_id="m", context_size=200_000, max_output=4096)
    state = AppState(model_meta=meta, last_turn_tokens=100_000)
    assert StatusFooter._ctx_pct(state) == 50.0
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/ui/test_status_footer.py -v`
Expected: FAIL with `ImportError: No module named 'poor_code.ui.widgets.status_footer'`.

- [ ] **Step 3: Implement StatusFooter widget**

Create `src/poor_code/ui/widgets/status_footer.py`:

```python
"""Bottom status bar — cumulative session usage + context-fill %.

Reactive on AppState. Color tier (normal/warn/danger) follows pi's
threshold: <70% / 70-90% / >90%.
"""
from __future__ import annotations

from textual.widgets import Static

from poor_code.ui.store import AppState


def _k(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class StatusFooter(Static):
    """Renders one line: ↑in ↓out $cost pct/ctx model."""

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
        return (
            f" ↑ {_k(u.input_tokens)}  ↓ {_k(u.output_tokens)}   "
            f"{cost}   {ctx}   {model}"
        )

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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/ui/test_status_footer.py -v`
Expected: all PASS.

### 5.2 Mount StatusFooter in ChatScreen

- [ ] **Step 5: Modify ChatScreen.compose**

In `src/poor_code/ui/screens/chat.py`, add the import and the mount:

```python
from textual.app import ComposeResult
from textual.screen import Screen

from poor_code.ui.widgets.chat_log import ChatLog
from poor_code.ui.widgets.prompt_box import PromptBox
from poor_code.ui.widgets.status_footer import StatusFooter


class ChatScreen(Screen):
    def compose(self) -> ComposeResult:
        yield ChatLog(id="chat-log")
        yield PromptBox()
        yield StatusFooter(id="status-footer")
```

- [ ] **Step 6: Add CSS for StatusFooter**

In `src/poor_code/ui/styles/app.tcss`, append at end:

```css
.status-footer {
    dock: bottom;
    height: 1;
    color: $text-muted;
    padding: 0 1;
}

.status-footer.warn {
    color: $warning;
}

.status-footer.danger {
    color: $error;
}
```

- [ ] **Step 7: Run the existing app smoke test (if any) and the full suite**

Run: `pytest -x`
Expected: PASS. No new test required for the mount — the unit tests in 5.1 cover behavior.

### 5.3 TurnBlock — per-turn footer (static first, then ticking)

We split this into two halves: first add the static footer that shows the final `model · duration` when the turn is done. Then add the live ticking timer that shows `model · X.Xs` while running.

- [ ] **Step 8: Write failing test for static footer text formatter**

Append to `tests/ui/test_chat_log.py`:

```python
import time

from poor_code.ui.store import TurnView
from poor_code.ui.widgets.chat_log import _format_turn_footer


def test_format_turn_footer_done_uses_duration_and_model():
    t = TurnView(
        turn_id="t1", cmd_id="c1", user_text="hi",
        status="done", duration_sec=1.234, model="gpt-4o",
    )
    assert _format_turn_footer(t, fallback_model="ignored") == "  gpt-4o · 1.2s"


def test_format_turn_footer_running_uses_elapsed_and_fallback_model():
    now = time.monotonic()
    t = TurnView(
        turn_id="t1", cmd_id="c1", user_text="hi",
        status="running", started_at=now - 3.0, model=None,
    )
    text = _format_turn_footer(t, fallback_model="gpt-4o")
    # Elapsed should be ~3.0s — assert close, not exact, to allow scheduling jitter.
    assert text.startswith("  gpt-4o · ")
    assert "3." in text or "2." in text  # ~3 seconds give-or-take


def test_format_turn_footer_pending_returns_empty():
    t = TurnView(turn_id=None, cmd_id="c1", user_text="hi", status="pending")
    assert _format_turn_footer(t, fallback_model="gpt-4o") == ""


def test_format_turn_footer_failed_with_duration_shown():
    t = TurnView(
        turn_id="t1", cmd_id="c1", user_text="hi",
        status="failed", duration_sec=0.5, model="gpt-4o",
        error="boom",
    )
    assert _format_turn_footer(t, fallback_model="ignored") == "  gpt-4o · 0.5s"
```

- [ ] **Step 9: Run tests to verify failure**

Run: `pytest tests/ui/test_chat_log.py::test_format_turn_footer_done_uses_duration_and_model -v`
Expected: FAIL — `_format_turn_footer` not defined.

- [ ] **Step 10: Add `_format_turn_footer` helper to chat_log.py**

In `src/poor_code/ui/widgets/chat_log.py`, add `import time` at top of file, and add the helper as a module-level function (above `TurnBlock`):

```python
def _format_turn_footer(turn, fallback_model: str) -> str:
    """One-line dim footer under an assistant turn. Shows `<model> · <duration>s`.
    During `running`, duration is live-elapsed from `turn.started_at`.
    During `done`/`failed`, duration is the authoritative `turn.duration_sec`.
    `fallback_model` is used while the turn is running (turn.model not yet set
    by TurnEnded)."""
    if turn.status == "pending":
        return ""
    model = turn.model or fallback_model or ""
    if turn.status == "running":
        if turn.started_at is None:
            return ""
        elapsed = time.monotonic() - turn.started_at
        return f"  {model} · {elapsed:.1f}s"
    # done or failed
    if turn.duration_sec is None:
        return ""
    return f"  {model} · {turn.duration_sec:.1f}s"
```

- [ ] **Step 11: Run formatter tests to verify pass**

Run: `pytest tests/ui/test_chat_log.py::test_format_turn_footer_done_uses_duration_and_model tests/ui/test_chat_log.py::test_format_turn_footer_running_uses_elapsed_and_fallback_model tests/ui/test_chat_log.py::test_format_turn_footer_pending_returns_empty tests/ui/test_chat_log.py::test_format_turn_footer_failed_with_duration_shown -v`
Expected: all PASS.

### 5.4 TurnBlock — mount the footer Static and wire to compose/refresh

- [ ] **Step 12: Modify TurnBlock.compose to yield the footer Static**

In `src/poor_code/ui/widgets/chat_log.py`, update `TurnBlock.compose`:

```python
def compose(self) -> ComposeResult:
    turn = self._turn
    yield Static(turn.user_text, classes="user-msg")
    for seg in turn.segments:
        yield self._make_segment_widget(seg)
    if turn.status == "failed" and turn.error:
        yield Static(f"  error: {turn.error}", classes="turn-error")
    yield Static(
        _format_turn_footer(turn, fallback_model=self._current_model()),
        classes="turn-footer",
        id="turn-footer",
    )

def _current_model(self) -> str:
    return getattr(self.app, "app_state", None) and self.app.app_state.model or ""
```

- [ ] **Step 13: Modify TurnBlock.refresh_from to update footer text + status-class re-sync**

Still in `src/poor_code/ui/widgets/chat_log.py`, at the END of `refresh_from()` (after the error block, before the function returns), add:

```python
    # --- per-turn footer (live ticking handled by interval; this updates
    # immediately on every state push so done→duration is reflected at once).
    footers = list(self.query("#turn-footer"))
    if footers:
        footers[0].update(_format_turn_footer(turn, fallback_model=self._current_model()))
```

- [ ] **Step 14: Add CSS for `.turn-footer`**

Append to `src/poor_code/ui/styles/app.tcss`:

```css
.turn-footer {
    color: $text-muted;
    height: 1;
    margin-top: 0;
    margin-bottom: 1;
}
```

- [ ] **Step 15: Run full suite to catch any rendering regressions**

Run: `pytest -x`
Expected: PASS.

### 5.5 TurnBlock — live ticking timer while running

- [ ] **Step 16: Write failing test for ticking behavior (functional, time-based)**

Append to `tests/ui/test_chat_log.py`:

```python
import asyncio

import pytest
from textual.app import App

from poor_code.ui.store import AppState, TurnView
from poor_code.ui.widgets.chat_log import TurnBlock


class _Harness(App):
    """Minimal App with reactive app_state, just enough to host TurnBlock."""
    def __init__(self, turn: TurnView):
        super().__init__()
        self._turn = turn

    def compose(self):
        yield TurnBlock(self._turn)

    @property
    def app_state(self) -> AppState:
        return AppState(model="gpt-4o")


@pytest.mark.asyncio
async def test_turn_block_ticks_footer_while_running():
    """While status='running', the footer should update every ~100ms with
    a fresh elapsed value."""
    started = __import__("time").monotonic()
    turn = TurnView(
        turn_id="t1", cmd_id="c1", user_text="hi",
        status="running", started_at=started, model=None,
    )
    app = _Harness(turn)
    async with app.run_test() as pilot:
        await pilot.pause(0.0)
        block = app.query_one(TurnBlock)
        footer = block.query_one("#turn-footer")
        first = str(footer.renderable)
        await pilot.pause(0.25)  # let the timer fire at least twice
        second = str(footer.renderable)
        assert first != second   # text moved on
        assert "gpt-4o" in second
```

- [ ] **Step 17: Run test — expect failure**

Run: `pytest tests/ui/test_chat_log.py::test_turn_block_ticks_footer_while_running -v`
Expected: FAIL — text doesn't change without a timer.

- [ ] **Step 18: Wire a Textual interval timer in TurnBlock**

In `src/poor_code/ui/widgets/chat_log.py`, modify `TurnBlock`:

Add a `_tick_timer` attribute initialized in `__init__`:
```python
def __init__(self, turn) -> None:
    super().__init__(classes="turn-block")
    self._turn = turn
    self._tick_timer = None
```

Add `on_mount` (or extend existing one — currently TurnBlock has no on_mount; add this method):
```python
def on_mount(self) -> None:
    if self._turn.status == "running":
        self._start_tick()

def on_unmount(self) -> None:
    self._stop_tick()

def _start_tick(self) -> None:
    if self._tick_timer is None:
        self._tick_timer = self.set_interval(0.1, self._tick_footer)
        self._tick_footer()

def _stop_tick(self) -> None:
    if self._tick_timer is not None:
        self._tick_timer.stop()
        self._tick_timer = None

def _tick_footer(self) -> None:
    footer = self.query_one("#turn-footer")
    footer.update(_format_turn_footer(self._turn, fallback_model=self._current_model()))
```

At the end of `refresh_from`, after updating the footer text in-place, add the start/stop transitions:
```python
    # Start/stop the live tick based on status transition.
    if turn.status == "running" and self._tick_timer is None:
        self._start_tick()
    elif turn.status != "running" and self._tick_timer is not None:
        self._stop_tick()
        # one final update so the authoritative duration_sec lands.
        footers = list(self.query("#turn-footer"))
        if footers:
            footers[0].update(_format_turn_footer(turn, fallback_model=self._current_model()))
```

- [ ] **Step 19: Run the ticking test to verify pass**

Run: `pytest tests/ui/test_chat_log.py::test_turn_block_ticks_footer_while_running -v`
Expected: PASS.

- [ ] **Step 20: Full suite**

Run: `pytest -x`
Expected: PASS.

### 5.6 Manual UI smoke test

- [ ] **Step 21: Launch the app and verify**

Run: `poor-code`

Verify:
1. Lower-left status footer shows `↑ 0  ↓ 0   $0.0000   ?/?   <model>` initially.
2. After `/login` completes and a model is selected, the footer's ctx fragment updates to e.g. `0%/128.0k`.
3. After sending a prompt and getting a response:
   - The status footer's tokens, cost, and ctx% update.
   - A dim line below the assistant message reads `<model> · <duration>s`.
4. While a response is streaming, the dim line ticks visibly (every 100ms).
5. If you send 5+ messages, ctx% creeps up. Threshold colors: normal → muted, >70% → warn, >90% → danger.

If anything is misaligned, file the visual fix as a follow-up — do not block this task on tcss tweaks.

### 5.7 Commit Task 5

- [ ] **Step 22: Commit**

```bash
git add src/poor_code/ui/widgets/chat_log.py \
        src/poor_code/ui/widgets/status_footer.py \
        src/poor_code/ui/screens/chat.py \
        src/poor_code/ui/styles/app.tcss \
        tests/ui/test_status_footer.py \
        tests/ui/test_chat_log.py
git commit -m "feat(ui): status footer + per-turn live duration line"
```

---

## Post-implementation verification

- [ ] **Step 1: Run the full test suite**

Run: `pytest`
Expected: all green.

- [ ] **Step 2: Verify the snapshot file is committed**

Run: `git ls-files src/poor_code/provider/_models_snapshot.json`
Expected: the path is listed.

- [ ] **Step 3: Verify the spec and plan are committed**

Run: `git ls-files docs/superpowers/specs/2026-05-25-chat-improvements-design.md docs/superpowers/plans/2026-05-25-chat-improvements.md`
Expected: both listed.

- [ ] **Step 4: Quick `git log` review**

Run: `git log --oneline -10`
Expected: 5 feature commits in order (registry → usage parsing → agent → store → UI), one spec/plan commit, all on `main` or the feature branch.

---

## Behavioral invariants (re-verify after implementation)

These are the spec's §11 matrix. If any of these break, ship is blocked.

1. **Unknown model** → `DEFAULT_META` applies; ctx_size=128k; cost=0.
2. **Pricing=None (Ollama local)** → cost=0, token counts still flow.
3. **Provider doesn't send usage** → `UsageUpdated` not emitted; footer keeps prior values.
4. **ctx% < 70%** → normal color; **70–90%** → warn; **>90%** → danger.
5. **Turn fails mid-stream** → duration captured to the failure point; model = config.model.
6. **Cancelled turn (Ctrl+C)** → `TurnFailed` path; duration = elapsed to cancellation.
7. **duration_sec ≥ 0** (monotonic guarantee).

---

## Future work (out of scope here)

- `settings.json` per-user pricing override (deep-merge over snapshot).
- Snapshot auto-refresh / `/models refresh` command.
- Reasoning + cache-read/write cost columns.
- Runtime model switch → re-lookup `model_meta`.
- Compaction-aware ctx% (subtract trimmed content).
