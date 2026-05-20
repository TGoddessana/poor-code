# First Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `EchoAgent` with a real `Agent` class that calls Ollama Cloud via an OpenAI Chat-compatible protocol, executes registered tools (starting with `read`), and feeds tool results back to the model until it produces a final message.

**Architecture:** opencode-style 4-axis Provider decomposition (Protocol / Endpoint / Auth / Framing). One Protocol implemented (`OpenAIChat`), one Provider wrapper (`ollama_cloud`). Tool layer mirrors opencode's `Tool` interface — pydantic params, `ToolContext`, `ExecuteResult`. Substitution for tests happens at `LLMClient`, not at `Agent`.

**Tech Stack:** Python 3.14, `httpx` (async HTTP), `pydantic` (tool schemas), `respx` (HTTP mocking for tests), `pytest` + `pytest-asyncio` (existing), `textual` (existing, untouched).

**Spec:** `docs/superpowers/specs/2026-05-20-first-agent-loop-design.md`

**Important pre-existing facts that affect the plan:**

1. `src/poor_code/messages.py` **already defines** tool-call Events: `ToolCallStarted(turn_id, tool_call_id, tool_name, args: dict)`, `ToolCallFinished(turn_id, tool_call_id, result)`, `ToolCallFailed(turn_id, tool_call_id, error)`. The Store reducer and `ChatLog` widget already handle them. **Use these existing names verbatim — do not add new ones.** This deviates from the spec's section 7 wording (`ToolCallCompleted`, with `output_preview`); the existing names win because they're already wired end-to-end.
2. `tests/ui/test_app_flow.py` uses a duck-typed `ScriptedAgent` injected via `PoorCodeApp(agent=...)`. The new `Agent` class must keep the same `async def run(self, cmd, cancel)` async-generator signature.
3. `pyproject.toml` requires Python 3.14. `match` statements, PEP 695 generics, `type` statement, and frozen dataclasses are available.
4. There is **no `Agent` Protocol after this change** — `src/poor_code/domain/agent.py` is rewritten from a Protocol into a concrete `Agent` class.

---

## File Structure

After this plan, the project layout will be:

```
src/poor_code/
├── app.py                              (unchanged)
├── cli.py                              MODIFIED: wires real Agent
├── messages.py                         (unchanged — Events already exist)
├── domain/
│   ├── __init__.py
│   ├── agent.py                        REWRITTEN: Agent class
│   └── tool/                           NEW PACKAGE
│       ├── __init__.py
│       ├── base.py                     Tool Protocol, ToolContext, ExecuteResult, PermissionRequest
│       ├── registry.py                 ToolRegistry
│       └── read.py                     ReadTool
├── provider/                           NEW PACKAGE
│   ├── __init__.py
│   ├── auth.py                         Auth Protocol + BearerAuth
│   ├── client.py                       LLMClient
│   ├── events.py                       LLMEvent union
│   ├── framing.py                      Framing Protocol + SseFraming
│   ├── route.py                        Route dataclass
│   ├── protocols/
│   │   ├── __init__.py
│   │   └── openai_chat.py              OpenAIChat
│   └── providers/
│       ├── __init__.py
│       └── ollama_cloud.py             thin factory
└── ui/                                 (unchanged)

tests/
├── conftest.py                         (unchanged)
├── provider/                           NEW
│   ├── __init__.py
│   ├── fakes.py                        FakeLLMClient (reused by domain tests)
│   ├── test_auth.py
│   ├── test_framing.py
│   ├── test_openai_chat.py
│   └── test_client.py
├── domain/
│   ├── __init__.py
│   ├── test_agent.py                   NEW (Agent + FakeLLMClient scenarios)
│   └── tool/                           NEW
│       ├── __init__.py
│       ├── test_read.py
│       └── test_registry.py
└── ui/
    └── test_app_flow.py                MIGRATED to Agent + FakeLLMClient

DELETE:
  src/poor_code/domain/echo_agent.py
  tests/domain/test_echo_agent.py
```

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add runtime + dev dependencies**

Edit `pyproject.toml` — add `httpx` and `pydantic` to `dependencies`, add `respx` to dev group:

```toml
dependencies = [
    "textual>=8.2.7",
    "httpx>=0.27",
    "pydantic>=2.9",
]

[dependency-groups]
dev = [
    "textual-dev>=1.8.0",
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
]
```

- [ ] **Step 2: Install**

Run: `uv sync`
Expected: exits 0, lockfile updated.

- [ ] **Step 3: Sanity import check**

Run: `uv run python -c "import httpx, pydantic, respx; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add httpx, pydantic, respx for provider/tool layer"
```

---

## Task 2: Provider events

**Files:**
- Create: `src/poor_code/provider/__init__.py`
- Create: `src/poor_code/provider/events.py`
- Create: `tests/provider/__init__.py`
- Create: `tests/provider/test_events.py`

`LLMEvent` is the provider-neutral stream item the `LLMClient` produces. Adding Anthropic later means another Protocol implementation emitting these same events — `Agent` doesn't change.

- [ ] **Step 1: Write the failing test**

Create `tests/provider/__init__.py` empty. Create `tests/provider/test_events.py`:

```python
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)


def test_text_delta_is_llm_event():
    ev = TextDelta(text="hi")
    assert isinstance(ev, LLMEvent)
    assert ev.text == "hi"


def test_tool_call_started_carries_id_and_name():
    ev = ToolCallStarted(call_id="c1", name="read")
    assert ev.call_id == "c1"
    assert ev.name == "read"


def test_tool_call_input_delta_carries_partial_json():
    ev = ToolCallInputDelta(call_id="c1", json_delta='{"pa')
    assert ev.json_delta == '{"pa'


def test_finished_reason_values():
    for r in ("stop", "tool_calls", "length", "error"):
        ev = FinishedReason(reason=r)
        assert ev.reason == r


def test_tool_call_ended_carries_id():
    assert ToolCallEnded(call_id="c1").call_id == "c1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/provider/test_events.py -v`
Expected: `ModuleNotFoundError: No module named 'poor_code.provider'`.

- [ ] **Step 3: Implement**

Create `src/poor_code/provider/__init__.py` empty. Create `src/poor_code/provider/events.py`:

```python
"""Provider-neutral stream events. Every concrete Protocol (OpenAIChat,
AnthropicMessages, ...) parses its native chunks into this union, so the
Agent loop never sees provider shapes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LLMEvent:
    """Marker base."""


@dataclass(frozen=True)
class TextDelta(LLMEvent):
    text: str


@dataclass(frozen=True)
class ToolCallStarted(LLMEvent):
    call_id: str
    name: str


@dataclass(frozen=True)
class ToolCallInputDelta(LLMEvent):
    call_id: str
    json_delta: str


@dataclass(frozen=True)
class ToolCallEnded(LLMEvent):
    call_id: str


@dataclass(frozen=True)
class FinishedReason(LLMEvent):
    reason: Literal["stop", "tool_calls", "length", "error"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/provider/test_events.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/provider/__init__.py src/poor_code/provider/events.py \
        tests/provider/__init__.py tests/provider/test_events.py
git commit -m "feat(provider): add LLMEvent union (text/tool-call/finish)"
```

---

## Task 3: BearerAuth

**Files:**
- Create: `src/poor_code/provider/auth.py`
- Create: `tests/provider/test_auth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/provider/test_auth.py`:

```python
import pytest

from poor_code.provider.auth import BearerAuth, MissingApiKey


def test_bearer_auth_apply_sets_authorization_header():
    auth = BearerAuth(token="sk-test")
    headers: dict[str, str] = {}
    auth.apply(headers)
    assert headers["Authorization"] == "Bearer sk-test"


def test_bearer_auth_from_env_reads_var(monkeypatch):
    monkeypatch.setenv("MY_KEY", "abc123")
    auth = BearerAuth.from_env("MY_KEY")
    assert auth.token == "abc123"


def test_bearer_auth_from_env_missing_raises(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    with pytest.raises(MissingApiKey, match="MY_KEY"):
        BearerAuth.from_env("MY_KEY")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/provider/test_auth.py -v`
Expected: `ModuleNotFoundError: No module named 'poor_code.provider.auth'`.

- [ ] **Step 3: Implement**

Create `src/poor_code/provider/auth.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class MissingApiKey(RuntimeError):
    def __init__(self, var: str) -> None:
        super().__init__(f"environment variable {var!r} is not set")
        self.var = var


@runtime_checkable
class Auth(Protocol):
    def apply(self, headers: dict[str, str]) -> None: ...


@dataclass(frozen=True)
class BearerAuth:
    token: str

    @classmethod
    def from_env(cls, var: str) -> "BearerAuth":
        token = os.environ.get(var)
        if not token:
            raise MissingApiKey(var)
        return cls(token)

    def apply(self, headers: dict[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self.token}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/provider/test_auth.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/provider/auth.py tests/provider/test_auth.py
git commit -m "feat(provider): add Auth Protocol + BearerAuth (from_env)"
```

---

## Task 4: SseFraming

**Files:**
- Create: `src/poor_code/provider/framing.py`
- Create: `tests/provider/test_framing.py`

SSE = Server-Sent Events. The OpenAI streaming endpoint sends lines like `data: {...}\n\n`, terminated by `data: [DONE]\n\n`. `SseFraming.frames()` consumes raw bytes from an httpx stream and yields each JSON payload (or stops on `[DONE]`).

- [ ] **Step 1: Write the failing test**

Create `tests/provider/test_framing.py`:

```python
import pytest

from poor_code.provider.framing import SseFraming


async def _aiter(items):
    for x in items:
        yield x


@pytest.mark.asyncio
async def test_sse_framing_splits_data_lines():
    raw = [
        b'data: {"a":1}\n\n',
        b'data: {"b":2}\n\n',
        b"data: [DONE]\n\n",
    ]
    framing = SseFraming()
    out = [chunk async for chunk in framing.frames(_aiter(raw))]
    assert out == [b'{"a":1}', b'{"b":2}']


@pytest.mark.asyncio
async def test_sse_framing_handles_split_across_reads():
    raw = [b'data: {"a":', b'1}\n\n', b"data: [DONE]\n\n"]
    framing = SseFraming()
    out = [chunk async for chunk in framing.frames(_aiter(raw))]
    assert out == [b'{"a":1}']


@pytest.mark.asyncio
async def test_sse_framing_ignores_blank_and_comment_lines():
    raw = [b": ping\n\n", b'data: {"a":1}\n\n', b"data: [DONE]\n\n"]
    framing = SseFraming()
    out = [chunk async for chunk in framing.frames(_aiter(raw))]
    assert out == [b'{"a":1}']
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/provider/test_framing.py -v`
Expected: `ModuleNotFoundError: No module named 'poor_code.provider.framing'`.

- [ ] **Step 3: Implement**

Create `src/poor_code/provider/framing.py`:

```python
"""Server-Sent Events framing.

Consumes raw byte chunks from an httpx stream and yields each `data:` payload
as bytes. Terminates on `data: [DONE]`. Ignores blank lines and `:` comments
per the SSE spec.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol


class Framing(Protocol):
    async def frames(self, byte_stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]: ...


class SseFraming:
    async def frames(
        self, byte_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[bytes]:
        buf = b""
        async for chunk in byte_stream:
            buf += chunk
            while b"\n\n" in buf:
                event, buf = buf.split(b"\n\n", 1)
                payload = self._extract_data(event)
                if payload is None:
                    continue
                if payload == b"[DONE]":
                    return
                yield payload

    @staticmethod
    def _extract_data(event: bytes) -> bytes | None:
        # An SSE event can have multiple lines; we only care about `data: ...`.
        data_parts: list[bytes] = []
        for line in event.split(b"\n"):
            if not line or line.startswith(b":"):
                continue
            if line.startswith(b"data:"):
                data_parts.append(line[5:].lstrip())
        if not data_parts:
            return None
        return b"\n".join(data_parts)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/provider/test_framing.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/provider/framing.py tests/provider/test_framing.py
git commit -m "feat(provider): add SseFraming for OpenAI-style data: chunks"
```

---

## Task 5: Route dataclass

**Files:**
- Create: `src/poor_code/provider/route.py`

A `Route` simply groups the four axes. No tests — it's a value object with no behavior.

- [ ] **Step 1: Implement**

Create `src/poor_code/provider/route.py`:

```python
"""A Route is the (Protocol, Endpoint, Auth, Framing) tuple that fully
describes how to talk to one LLM HTTP endpoint. Providers (`providers/*.py`)
build Routes and hand them to `LLMClient`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from poor_code.provider.auth import Auth
from poor_code.provider.framing import Framing

if TYPE_CHECKING:
    from poor_code.provider.protocols.openai_chat import Protocol


@dataclass(frozen=True)
class Route:
    protocol: "Protocol"
    endpoint: str       # URL path, e.g. "/v1/chat/completions"
    auth: Auth
    framing: Framing
```

- [ ] **Step 2: Smoke import check**

Run: `uv run python -c "from poor_code.provider.route import Route; print(Route)"`
Expected: prints `<class 'poor_code.provider.route.Route'>`.

- [ ] **Step 3: Commit**

```bash
git add src/poor_code/provider/route.py
git commit -m "feat(provider): add Route dataclass (4-axis grouping)"
```

---

## Task 6: OpenAIChat protocol — build_body

**Files:**
- Create: `src/poor_code/provider/protocols/__init__.py`
- Create: `src/poor_code/provider/protocols/openai_chat.py`
- Create: `tests/provider/test_openai_chat.py`

- [ ] **Step 1: Write the failing test**

Create `tests/provider/test_openai_chat.py`:

```python
from poor_code.provider.protocols.openai_chat import OpenAIChat


def test_build_body_minimal():
    proto = OpenAIChat()
    body = proto.build_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="qwen2.5-coder:7b",
    )
    assert body == {
        "model": "qwen2.5-coder:7b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }


def test_build_body_with_tools_includes_tools_key():
    proto = OpenAIChat()
    tools_schema = [
        {
            "type": "function",
            "function": {"name": "read", "description": "d", "parameters": {}},
        }
    ]
    body = proto.build_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=tools_schema,
        model="m",
    )
    assert body["tools"] == tools_schema


def test_build_body_omits_tools_when_empty():
    proto = OpenAIChat()
    body = proto.build_body(messages=[], tools=[], model="m")
    assert "tools" not in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/provider/test_openai_chat.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement (build_body only — parse_chunk added next task)**

Create `src/poor_code/provider/protocols/__init__.py` empty. Create `src/poor_code/provider/protocols/openai_chat.py`:

```python
"""OpenAI Chat-Completions streaming protocol.

Covers all OpenAI-compatible endpoints: OpenAI itself, Ollama (cloud + local
`/v1/chat/completions`), llama.cpp `llama-server`, DeepSeek, Groq, Together,
xAI, OpenRouter, etc. Adding any of those means a new `providers/<name>.py`
that reuses this Protocol with a different baseURL.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Protocol as _PyProtocol

from poor_code.provider.events import LLMEvent


class Protocol(_PyProtocol):
    def build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]: ...

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]: ...


class OpenAIChat:
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
        }
        if tools:
            body["tools"] = tools
        return body

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
        # Implemented in Task 7.
        raise NotImplementedError
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/provider/test_openai_chat.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/provider/protocols/__init__.py \
        src/poor_code/provider/protocols/openai_chat.py \
        tests/provider/test_openai_chat.py
git commit -m "feat(provider): OpenAIChat.build_body for streaming requests"
```

---

## Task 7: OpenAIChat protocol — parse_chunk

**Files:**
- Modify: `src/poor_code/provider/protocols/openai_chat.py`
- Modify: `tests/provider/test_openai_chat.py`

OpenAI streaming sends JSON chunks like:

```json
{"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}
{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"read","arguments":""}}]},"finish_reason":null}]}
{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"path\":\"a\"}"}}]},"finish_reason":null}]}
{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}
```

Tool calls arrive piecewise: the first chunk for a given `index` carries `id` + `name`; subsequent chunks for the same `index` only carry `arguments` deltas. We translate this into our `ToolCallStarted` → `ToolCallInputDelta*` → `ToolCallEnded` events. `ToolCallEnded` fires when the `finish_reason` arrives (one per pending call, in index order).

- [ ] **Step 1: Add parse_chunk tests**

Append to `tests/provider/test_openai_chat.py`:

```python
def test_parse_text_delta():
    proto = OpenAIChat()
    events = list(
        proto.parse_chunk(
            {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
        )
    )
    from poor_code.provider.events import TextDelta
    assert events == [TextDelta(text="hi")]


def test_parse_tool_call_start_emits_started_then_input_delta():
    proto = OpenAIChat()
    events = list(
        proto.parse_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "read", "arguments": ""},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
        )
    )
    from poor_code.provider.events import ToolCallStarted
    assert events == [ToolCallStarted(call_id="call_1", name="read")]


def test_parse_tool_call_argument_delta():
    proto = OpenAIChat()
    # First chunk registers the call so parser knows index→call_id.
    list(proto.parse_chunk({
        "choices": [{
            "delta": {"tool_calls": [{
                "index": 0, "id": "call_1",
                "function": {"name": "read", "arguments": ""},
            }]},
            "finish_reason": None,
        }]
    }))
    events = list(proto.parse_chunk({
        "choices": [{
            "delta": {"tool_calls": [{
                "index": 0,
                "function": {"arguments": '{"path":"a"}'},
            }]},
            "finish_reason": None,
        }]
    }))
    from poor_code.provider.events import ToolCallInputDelta
    assert events == [ToolCallInputDelta(call_id="call_1", json_delta='{"path":"a"}')]


def test_parse_finish_emits_ended_for_open_calls_then_finished_reason():
    proto = OpenAIChat()
    list(proto.parse_chunk({
        "choices": [{
            "delta": {"tool_calls": [{
                "index": 0, "id": "call_1",
                "function": {"name": "read", "arguments": ""},
            }]},
            "finish_reason": None,
        }]
    }))
    events = list(proto.parse_chunk({
        "choices": [{"delta": {}, "finish_reason": "tool_calls"}]
    }))
    from poor_code.provider.events import FinishedReason, ToolCallEnded
    assert events == [
        ToolCallEnded(call_id="call_1"),
        FinishedReason(reason="tool_calls"),
    ]


def test_parse_finish_stop_with_no_open_calls():
    proto = OpenAIChat()
    events = list(proto.parse_chunk(
        {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    ))
    from poor_code.provider.events import FinishedReason
    assert events == [FinishedReason(reason="stop")]
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/provider/test_openai_chat.py -v`
Expected: 3 prior pass, 5 new fail with `NotImplementedError`.

- [ ] **Step 3: Implement parse_chunk**

Replace the `parse_chunk` body in `src/poor_code/provider/protocols/openai_chat.py`. Add an instance dict to track index→call_id. The full new file:

```python
"""OpenAI Chat-Completions streaming protocol.

Covers all OpenAI-compatible endpoints: OpenAI itself, Ollama (cloud + local
`/v1/chat/completions`), llama.cpp `llama-server`, DeepSeek, Groq, Together,
xAI, OpenRouter, etc. Adding any of those means a new `providers/<name>.py`
that reuses this Protocol with a different baseURL.
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol as _PyProtocol

from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)


class Protocol(_PyProtocol):
    def build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]: ...

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]: ...


class OpenAIChat:
    """Stateless across requests; the per-stream parse state lives on the
    instance returned by `for_stream()`. The bare `OpenAIChat()` instance
    used in build_body shares no state — clients call `for_stream()` once
    per HTTP request to get a fresh parser.
    """

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
        }
        if tools:
            body["tools"] = tools
        return body

    # parse_chunk holds per-stream state (index → call_id, open call order).
    # Callers should construct one OpenAIChat per stream OR call for_stream()
    # to get an isolated parser.
    def __init__(self) -> None:
        self._index_to_call: dict[int, str] = {}
        self._open_order: list[str] = []

    def for_stream(self) -> "OpenAIChat":
        return OpenAIChat()

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
        choices = chunk.get("choices") or []
        if not choices:
            return
        choice = choices[0]
        delta = choice.get("delta") or {}

        content = delta.get("content")
        if content:
            yield TextDelta(text=content)

        for tc in delta.get("tool_calls") or []:
            index = tc.get("index")
            fn = tc.get("function") or {}
            call_id = tc.get("id")
            name = fn.get("name")
            args = fn.get("arguments")

            if index is not None and call_id and name is not None and index not in self._index_to_call:
                # First chunk for this index: registers the call.
                self._index_to_call[index] = call_id
                self._open_order.append(call_id)
                yield ToolCallStarted(call_id=call_id, name=name)
                if args:
                    yield ToolCallInputDelta(call_id=call_id, json_delta=args)
                continue

            # Continuation chunk: argument delta only.
            if index is not None and index in self._index_to_call and args:
                yield ToolCallInputDelta(
                    call_id=self._index_to_call[index], json_delta=args
                )

        finish = choice.get("finish_reason")
        if finish:
            for call_id in self._open_order:
                yield ToolCallEnded(call_id=call_id)
            self._open_order.clear()
            yield FinishedReason(reason=finish)
```

- [ ] **Step 4: Run to verify all tests pass**

Run: `uv run pytest tests/provider/test_openai_chat.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/provider/protocols/openai_chat.py tests/provider/test_openai_chat.py
git commit -m "feat(provider): OpenAIChat.parse_chunk → LLMEvent stream"
```

---

## Task 8: LLMClient

**Files:**
- Create: `src/poor_code/provider/client.py`
- Create: `tests/provider/test_client.py`

`LLMClient.stream()` ties everything together: build the body, open an httpx stream with the route's headers and SSE framing, run each JSON chunk through the protocol's parser, yield `LLMEvent`s. Tests use `respx` to mock the HTTP layer.

- [ ] **Step 1: Write the failing test**

Create `tests/provider/test_client.py`:

```python
import json

import httpx
import pytest
import respx

from poor_code.provider.auth import BearerAuth
from poor_code.provider.client import LLMClient
from poor_code.provider.events import (
    FinishedReason,
    TextDelta,
    ToolCallEnded,
    ToolCallStarted,
)
from poor_code.provider.framing import SseFraming
from poor_code.provider.protocols.openai_chat import OpenAIChat
from poor_code.provider.route import Route


def _sse(chunks: list[dict]) -> bytes:
    out = b""
    for c in chunks:
        out += b"data: " + json.dumps(c).encode() + b"\n\n"
    out += b"data: [DONE]\n\n"
    return out


@pytest.mark.asyncio
@respx.mock
async def test_stream_text_only():
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="t"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")

    body = _sse([
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": " there"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body)
    )

    events = [
        ev async for ev in client.stream(messages=[{"role": "user", "content": "x"}], tools=[])
    ]
    assert events == [
        TextDelta(text="hi"),
        TextDelta(text=" there"),
        FinishedReason(reason="stop"),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_stream_sends_auth_header_and_streaming_body():
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="sk-xyz"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse([{"choices": [{"delta": {}, "finish_reason": "stop"}]}]),
        )

    respx.post("https://example.test/v1/chat/completions").mock(side_effect=_capture)
    [_ async for _ in client.stream(messages=[{"role": "user", "content": "x"}], tools=[])]

    assert captured["auth"] == "Bearer sk-xyz"
    assert captured["body"]["stream"] is True
    assert captured["body"]["model"] == "m"


@pytest.mark.asyncio
@respx.mock
async def test_stream_propagates_tool_call_events():
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="t"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")

    body = _sse([
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "read", "arguments": ""}}
        ]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"path":"a"}'}}
        ]}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body)
    )

    events = [ev async for ev in client.stream(messages=[], tools=[])]
    kinds = [type(e).__name__ for e in events]
    assert "ToolCallStarted" in kinds
    assert "ToolCallEnded" in kinds
    assert events[-1] == FinishedReason(reason="tool_calls")


@pytest.mark.asyncio
@respx.mock
async def test_stream_http_error_raises():
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="t"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(httpx.HTTPStatusError):
        [_ async for _ in client.stream(messages=[], tools=[])]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/provider/test_client.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `src/poor_code/provider/client.py`:

```python
"""LLMClient — assembles a Route + httpx.AsyncClient into a streaming API.

stream() is an async generator of provider-neutral LLMEvents. One instance
is reused across turns; each call to stream() opens a fresh HTTP request
and a fresh parser instance (so per-stream state in OpenAIChat is isolated).
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from poor_code.provider.events import LLMEvent
from poor_code.provider.route import Route


class LLMClient:
    def __init__(self, route: Route, base_url: str, model: str) -> None:
        self.route = route
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[LLMEvent]:
        parser = self.route.protocol.for_stream()  # fresh per-stream parser
        body = parser.build_body(messages=messages, tools=tools, model=self.model)
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        self.route.auth.apply(headers)
        url = self.base_url + self.route.endpoint

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None)) as http:
            async with http.stream("POST", url, headers=headers, json=body) as resp:
                resp.raise_for_status()
                async for payload in self.route.framing.frames(resp.aiter_bytes()):
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    for event in parser.parse_chunk(chunk):
                        yield event
```

- [ ] **Step 4: Run to verify all tests pass**

Run: `uv run pytest tests/provider/test_client.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run all provider tests**

Run: `uv run pytest tests/provider/ -v`
Expected: all green (17+ tests).

- [ ] **Step 6: Commit**

```bash
git add src/poor_code/provider/client.py tests/provider/test_client.py
git commit -m "feat(provider): LLMClient.stream — HTTP + framing + protocol"
```

---

## Task 9: Ollama Cloud provider

**Files:**
- Create: `src/poor_code/provider/providers/__init__.py`
- Create: `src/poor_code/provider/providers/ollama_cloud.py`
- Create: `tests/provider/test_ollama_cloud.py`

- [ ] **Step 1: Write the failing test**

Create `tests/provider/test_ollama_cloud.py`:

```python
import pytest

from poor_code.provider.auth import MissingApiKey
from poor_code.provider.client import LLMClient
from poor_code.provider.providers import ollama_cloud


def test_client_factory_requires_api_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with pytest.raises(MissingApiKey, match="OLLAMA_API_KEY"):
        ollama_cloud.client(model="qwen2.5-coder:7b")


def test_client_factory_builds_llm_client(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    client = ollama_cloud.client(model="qwen2.5-coder:7b")
    assert isinstance(client, LLMClient)
    assert client.model == "qwen2.5-coder:7b"
    assert client.base_url == "https://ollama.com"
    assert client.route.endpoint == "/v1/chat/completions"


def test_client_factory_accepts_custom_base_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    client = ollama_cloud.client(model="m", base_url="https://other.test")
    assert client.base_url == "https://other.test"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/provider/test_ollama_cloud.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `src/poor_code/provider/providers/__init__.py` empty. Create `src/poor_code/provider/providers/ollama_cloud.py`:

```python
"""Ollama Cloud — OpenAI Chat-compatible endpoint, Bearer auth.

Thin factory only: every poor-code Provider file should stay this small
(mirrors opencode's providers/*.ts pattern). Default model is overridable
at call site; do not hardcode here.
"""
from __future__ import annotations

from poor_code.provider.auth import BearerAuth
from poor_code.provider.client import LLMClient
from poor_code.provider.framing import SseFraming
from poor_code.provider.protocols.openai_chat import OpenAIChat
from poor_code.provider.route import Route

DEFAULT_BASE_URL = "https://ollama.com"


def client(model: str, base_url: str = DEFAULT_BASE_URL) -> LLMClient:
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth.from_env("OLLAMA_API_KEY"),
        framing=SseFraming(),
    )
    return LLMClient(route=route, base_url=base_url, model=model)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/provider/test_ollama_cloud.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/provider/providers/__init__.py \
        src/poor_code/provider/providers/ollama_cloud.py \
        tests/provider/test_ollama_cloud.py
git commit -m "feat(provider): Ollama Cloud factory (OpenAI-compat, Bearer)"
```

---

## Task 10: Tool base types

**Files:**
- Create: `src/poor_code/domain/tool/__init__.py`
- Create: `src/poor_code/domain/tool/base.py`
- Create: `tests/domain/tool/__init__.py`
- Create: `tests/domain/tool/test_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/domain/tool/__init__.py` empty. Create `tests/domain/tool/test_base.py`:

```python
import asyncio
from pathlib import Path

from pydantic import BaseModel

from poor_code.domain.tool.base import (
    ExecuteResult,
    PermissionRequest,
    Tool,
    ToolContext,
)


def test_execute_result_defaults():
    r = ExecuteResult(title="t", output="o")
    assert r.metadata == {}


def test_tool_context_fields():
    ev = asyncio.Event()
    async def stub_ask(req): return "allow"
    ctx = ToolContext(
        turn_id="T1", cancel=ev, cwd=Path("/tmp"), ask=stub_ask,
    )
    assert ctx.turn_id == "T1"
    assert ctx.cancel is ev
    assert ctx.cwd == Path("/tmp")


def test_permission_request_carries_tool_id_and_pattern():
    req = PermissionRequest(tool_id="read", pattern="/etc/*")
    assert req.tool_id == "read"
    assert req.pattern == "/etc/*"
    assert req.metadata == {}


def test_tool_protocol_runtime_checkable():
    class Args(BaseModel): pass
    class DummyTool:
        id = "dummy"
        description = "d"
        params = Args
        async def execute(self, args, ctx): return ExecuteResult(title="t", output="o")
    assert isinstance(DummyTool(), Tool)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/domain/tool/test_base.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `src/poor_code/domain/tool/__init__.py` empty. Create `src/poor_code/domain/tool/base.py`:

```python
"""Tool abstraction — mirror of opencode's Tool.Def in Python.

A Tool exposes a name+description, a pydantic params model (which becomes
the JSON schema sent to the LLM), and an async execute() that receives the
parsed args plus a ToolContext (cancel signal, cwd, permission ask hook).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass
class ExecuteResult:
    title: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionRequest:
    tool_id: str
    pattern: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    turn_id: str
    cancel: asyncio.Event
    cwd: Path
    ask: Callable[[PermissionRequest], Awaitable[Literal["allow", "deny"]]]


@runtime_checkable
class Tool(Protocol):
    id: str
    description: str
    params: type[BaseModel]

    async def execute(self, args: BaseModel, ctx: ToolContext) -> ExecuteResult: ...


async def allow_all(_: PermissionRequest) -> Literal["allow", "deny"]:
    """Stub `ask` implementation for first-stage. ReadTool doesn't call ask,
    but the Context still requires a callable. Replace with a real prompt
    when the permission UI lands.
    """
    return "allow"
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/domain/tool/test_base.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/domain/tool/__init__.py src/poor_code/domain/tool/base.py \
        tests/domain/tool/__init__.py tests/domain/tool/test_base.py
git commit -m "feat(tool): Tool Protocol + ToolContext + ExecuteResult"
```

---

## Task 11: ToolRegistry

**Files:**
- Create: `src/poor_code/domain/tool/registry.py`
- Create: `tests/domain/tool/test_registry.py`

The registry holds `name → Tool`, and exposes `schemas()` which returns the OpenAI-format tool list to pass to `LLMClient.stream(tools=...)`.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/tool/test_registry.py`:

```python
import pytest
from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult
from poor_code.domain.tool.registry import ToolRegistry, DuplicateToolId


class _Args(BaseModel):
    path: str = Field(description="file path")


class _DummyTool:
    id = "dummy"
    description = "a dummy tool"
    params = _Args
    async def execute(self, args, ctx):
        return ExecuteResult(title="t", output="o")


def test_get_returns_tool_or_none():
    reg = ToolRegistry([_DummyTool()])
    assert reg.get("dummy").id == "dummy"
    assert reg.get("missing") is None


def test_schemas_emits_openai_function_shape():
    reg = ToolRegistry([_DummyTool()])
    schemas = reg.schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "dummy"
    assert s["function"]["description"] == "a dummy tool"
    params = s["function"]["parameters"]
    assert params["type"] == "object"
    assert "path" in params["properties"]


def test_duplicate_id_raises():
    with pytest.raises(DuplicateToolId, match="dummy"):
        ToolRegistry([_DummyTool(), _DummyTool()])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/domain/tool/test_registry.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `src/poor_code/domain/tool/registry.py`:

```python
"""ToolRegistry — maps tool ids to Tool instances, emits the OpenAI-format
function-tool schema list that `LLMClient.stream(tools=...)` consumes.
"""
from __future__ import annotations

from typing import Any

from poor_code.domain.tool.base import Tool


class DuplicateToolId(ValueError):
    def __init__(self, tool_id: str) -> None:
        super().__init__(f"duplicate tool id: {tool_id!r}")
        self.tool_id = tool_id


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools:
            if t.id in self._tools:
                raise DuplicateToolId(t.id)
            self._tools[t.id] = t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.id,
                    "description": t.description,
                    "parameters": t.params.model_json_schema(),
                },
            }
            for t in self._tools.values()
        ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/domain/tool/test_registry.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/domain/tool/registry.py tests/domain/tool/test_registry.py
git commit -m "feat(tool): ToolRegistry (get + OpenAI-shaped schemas)"
```

---

## Task 12: ReadTool

**Files:**
- Create: `src/poor_code/domain/tool/read.py`
- Create: `tests/domain/tool/test_read.py`

- [ ] **Step 1: Write the failing test**

Create `tests/domain/tool/test_read.py`:

```python
import asyncio
from pathlib import Path

import pytest

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.read import ReadParams, ReadTool


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(turn_id="T", cancel=asyncio.Event(), cwd=cwd, ask=allow_all)


@pytest.mark.asyncio
async def test_read_small_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line one\nline two\n")
    tool = ReadTool()
    result = await tool.execute(ReadParams(path="hello.txt"), _ctx(tmp_path))
    assert result.title == str(f.resolve())
    assert result.output == "     1\tline one\n     2\tline two\n"


@pytest.mark.asyncio
async def test_read_with_start_and_limit(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("\n".join(f"L{i}" for i in range(1, 6)) + "\n")
    tool = ReadTool()
    result = await tool.execute(ReadParams(path="x.txt", start=2, limit=2), _ctx(tmp_path))
    assert result.output == "     2\tL2\n     3\tL3\n"


@pytest.mark.asyncio
async def test_read_missing_file_raises(tmp_path):
    tool = ReadTool()
    with pytest.raises(FileNotFoundError):
        await tool.execute(ReadParams(path="nope.txt"), _ctx(tmp_path))


@pytest.mark.asyncio
async def test_read_rejects_path_outside_cwd(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("nope")
    try:
        tool = ReadTool()
        with pytest.raises(PermissionError, match="outside cwd"):
            await tool.execute(ReadParams(path=str(outside)), _ctx(tmp_path))
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_read_honors_cancel(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("a\n")
    tool = ReadTool()
    ctx = _ctx(tmp_path)
    ctx.cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await tool.execute(ReadParams(path="x.txt"), ctx)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/domain/tool/test_read.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `src/poor_code/domain/tool/read.py`:

```python
"""ReadTool — read a single text file with line numbers (cat -n format).

Read-only; never calls ctx.ask (always safe). Refuses paths outside ctx.cwd.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext


class ReadParams(BaseModel):
    path: str = Field(description="File path. Relative paths resolve against the working dir.")
    start: int = Field(default=1, ge=1, description="1-indexed start line.")
    limit: int = Field(default=2000, ge=1, le=10000, description="Max lines to read.")


class ReadTool:
    id = "read"
    description = "Read a single text file with line numbers (cat -n format)."
    params = ReadParams

    async def execute(self, args: ReadParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError

        raw = Path(args.path)
        target = (ctx.cwd / raw).resolve() if not raw.is_absolute() else raw.resolve()
        cwd_resolved = ctx.cwd.resolve()
        if cwd_resolved != target and cwd_resolved not in target.parents:
            raise PermissionError(f"path outside cwd: {args.path}")

        if not target.is_file():
            raise FileNotFoundError(args.path)

        with target.open("r", encoding="utf-8", errors="replace") as fh:
            lines: list[str] = []
            for i, line in enumerate(fh, start=1):
                if i < args.start:
                    continue
                if i >= args.start + args.limit:
                    break
                lines.append(f"{i:>6}\t{line}")
                if not line.endswith("\n"):
                    lines[-1] += "\n"

        return ExecuteResult(title=str(target), output="".join(lines))
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/domain/tool/test_read.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/domain/tool/read.py tests/domain/tool/test_read.py
git commit -m "feat(tool): ReadTool — cat -n format, cwd-scoped, cancel-aware"
```

---

## Task 13: FakeLLMClient test fake

**Files:**
- Create: `tests/provider/fakes.py`

A shared test double. `Agent` tests and the migrated UI flow test both depend on it. Producing it once avoids duplication.

- [ ] **Step 1: Implement (no separate test — covered by callers)**

Create `tests/provider/fakes.py`:

```python
"""FakeLLMClient — scripted LLMEvent streams for testing Agent.

Use either:
  FakeLLMClient([[ev, ev, ev], [ev, ev]])    # list of rounds
or:
  FakeLLMClient.text_only("hello")           # convenience: one round of text
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Iterable

from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
)


class FakeLLMClient:
    def __init__(self, rounds: list[list[LLMEvent]]) -> None:
        self._rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []  # captured stream() args, for assertions

    @classmethod
    def text_only(cls, text: str) -> "FakeLLMClient":
        return cls([[TextDelta(text=text), FinishedReason(reason="stop")]])

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        if not self._rounds:
            raise AssertionError("FakeLLMClient.stream called more times than scripted")
        events = self._rounds.pop(0)
        for ev in events:
            yield ev
```

- [ ] **Step 2: Smoke import**

Run: `uv run python -c "from tests.provider.fakes import FakeLLMClient; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add tests/provider/fakes.py
git commit -m "test(provider): add FakeLLMClient for Agent tests"
```

---

## Task 14: Agent — text-only scenario (TDD baseline)

**Files:**
- Modify: `src/poor_code/domain/agent.py` (rewrite)
- Create: `tests/domain/test_agent.py`

This task introduces the new `Agent` class with the simplest scenario: text-only round, no tools. Following tasks add tool calls, multi-iteration, error handling, cancellation.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/test_agent.py`:

```python
import asyncio

import pytest

from poor_code.domain.agent import Agent
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    SendPrompt,
    TurnEnded,
    TurnStarted,
)
from tests.provider.fakes import FakeLLMClient


async def _collect(agent, cmd, cancel):
    return [ev async for ev in agent.run(cmd, cancel)]


@pytest.mark.asyncio
async def test_text_only_turn():
    llm = FakeLLMClient.text_only("hi there")
    agent = Agent(llm=llm, tools=ToolRegistry([]))
    events = await _collect(agent, SendPrompt(text="ping"), asyncio.Event())

    types = [type(ev).__name__ for ev in events]
    assert types == [
        "TurnStarted",
        "AssistantTextDelta",
        "AssistantMessageCompleted",
        "TurnEnded",
    ]
    assert isinstance(events[1], AssistantTextDelta) and events[1].text == "hi there"
    assert isinstance(events[2], AssistantMessageCompleted) and events[2].text == "hi there"
    assert llm.calls[0]["messages"] == [{"role": "user", "content": "ping"}]


@pytest.mark.asyncio
async def test_history_accumulates_across_turns():
    rounds = [
        [
            # turn 1
            __import__("poor_code.provider.events", fromlist=["TextDelta"]).TextDelta(text="one"),
            __import__("poor_code.provider.events", fromlist=["FinishedReason"]).FinishedReason(reason="stop"),
        ],
        [
            # turn 2
            __import__("poor_code.provider.events", fromlist=["TextDelta"]).TextDelta(text="two"),
            __import__("poor_code.provider.events", fromlist=["FinishedReason"]).FinishedReason(reason="stop"),
        ],
    ]
    llm = FakeLLMClient(rounds)
    agent = Agent(llm=llm, tools=ToolRegistry([]))
    await _collect(agent, SendPrompt(text="A"), asyncio.Event())
    await _collect(agent, SendPrompt(text="B"), asyncio.Event())
    second_messages = llm.calls[1]["messages"]
    assert second_messages == [
        {"role": "user", "content": "A"},
        {"role": "assistant", "content": "one"},
        {"role": "user", "content": "B"},
    ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/domain/test_agent.py -v`
Expected: import error — `agent.py` still has the old Protocol-only body.

- [ ] **Step 3: Rewrite `agent.py`**

Replace the entire contents of `src/poor_code/domain/agent.py`:

```python
"""Agent — the inner loop. Calls the LLM, executes tools, feeds results
back, until the model produces a final assistant message (no tool_calls)
or MAX_ITERATIONS is reached.

There is no Agent Protocol: tests substitute at the LLMClient boundary
via FakeLLMClient, not at the Agent boundary.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.registry import ToolRegistry
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
)
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted as ProviderToolCallStarted,
)


MAX_ITERATIONS = 8


@runtime_checkable
class _LLMClientLike(Protocol):
    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]: ...


@dataclass
class _PendingCall:
    call_id: str
    name: str
    args_json: str = ""


class Agent:
    def __init__(self, llm: _LLMClientLike, tools: ToolRegistry) -> None:
        self.llm = llm
        self.tools = tools
        self.history: list[dict[str, Any]] = []

    async def run(self, cmd: Command, cancel: asyncio.Event) -> AsyncIterator[Event]:
        turn_id = uuid.uuid4().hex
        cmd_id = getattr(cmd, "cmd_id", "")

        user_text = self._cmd_to_text(cmd)
        if user_text is None:
            yield TurnFailed(turn_id=turn_id, error=f"unsupported command: {type(cmd).__name__}")
            return

        self.history.append({"role": "user", "content": user_text})
        yield TurnStarted(cmd_id=cmd_id, turn_id=turn_id)

        ctx = ToolContext(
            turn_id=turn_id, cancel=cancel, cwd=Path.cwd(), ask=allow_all
        )

        for _iteration in range(MAX_ITERATIONS):
            if cancel.is_set():
                yield TurnFailed(turn_id=turn_id, error="cancelled")
                return

            assistant_text = ""
            pending: dict[str, _PendingCall] = {}
            call_order: list[str] = []

            try:
                async for ev in self.llm.stream(
                    messages=self.history, tools=self.tools.schemas()
                ):
                    if cancel.is_set():
                        yield TurnFailed(turn_id=turn_id, error="cancelled")
                        return
                    match ev:
                        case TextDelta(text=t):
                            assistant_text += t
                            yield AssistantTextDelta(turn_id=turn_id, text=t)
                        case ProviderToolCallStarted(call_id=cid, name=name):
                            pending[cid] = _PendingCall(call_id=cid, name=name)
                            call_order.append(cid)
                        case ToolCallInputDelta(call_id=cid, json_delta=delta):
                            if cid in pending:
                                pending[cid].args_json += delta
                        case ToolCallEnded():
                            pass  # finalization handled at FinishedReason
                        case FinishedReason():
                            break
            except Exception as e:
                yield TurnFailed(turn_id=turn_id, error=f"{type(e).__name__}: {e}")
                return

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": assistant_text}
            if call_order:
                assistant_msg["tool_calls"] = [
                    {
                        "id": cid,
                        "type": "function",
                        "function": {
                            "name": pending[cid].name,
                            "arguments": pending[cid].args_json or "{}",
                        },
                    }
                    for cid in call_order
                ]
            self.history.append(assistant_msg)

            if not call_order:
                yield AssistantMessageCompleted(turn_id=turn_id, text=assistant_text)
                yield TurnEnded(turn_id=turn_id)
                return

            # Execute tool calls in order, feed results back, loop again.
            for cid in call_order:
                async for ev in self._execute_tool_call(turn_id, pending[cid], ctx):
                    yield ev

        # Max iterations exhausted.
        yield TurnEnded(turn_id=turn_id)

    async def _execute_tool_call(
        self, turn_id: str, call: _PendingCall, ctx: ToolContext
    ) -> AsyncIterator[Event]:
        """Implemented in Task 15. For now, mark all calls failed so the
        loop terminates cleanly under text-only tests.
        """
        yield ToolCallFailed(
            turn_id=turn_id,
            tool_call_id=call.call_id,
            error="tool execution not implemented",
        )
        self.history.append({
            "role": "tool",
            "tool_call_id": call.call_id,
            "content": "ERROR: tool execution not implemented",
        })

    @staticmethod
    def _cmd_to_text(cmd: Command) -> str | None:
        match cmd:
            case SendPrompt(text=t):
                return t
            case RunSlashCommand(name=n, args=a):
                return f"/{n} {' '.join(a)}".strip()
            case _:
                return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/domain/test_agent.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/domain/agent.py tests/domain/test_agent.py
git commit -m "feat(agent): Agent class — text-only scenario (no tool exec yet)"
```

---

## Task 15: Agent — tool execution + recovery

**Files:**
- Modify: `src/poor_code/domain/agent.py` — replace `_execute_tool_call`
- Modify: `tests/domain/test_agent.py` — add scenarios B, C

- [ ] **Step 1: Add the failing tests**

Append to `tests/domain/test_agent.py`:

```python
from poor_code.domain.tool.base import ExecuteResult
from poor_code.domain.tool.read import ReadParams
from poor_code.messages import ToolCallFinished, ToolCallStarted as MsgToolCallStarted
from poor_code.provider.events import (
    FinishedReason,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted as ProviderToolCallStarted,
)


class _FakeReadTool:
    id = "read"
    description = "fake"
    params = ReadParams

    def __init__(self, output: str = "FILE CONTENT") -> None:
        self.output = output
        self.calls: list[ReadParams] = []

    async def execute(self, args, ctx):
        self.calls.append(args)
        return ExecuteResult(title="t", output=self.output)


@pytest.mark.asyncio
async def test_tool_call_executed_then_followup_text():
    tool = _FakeReadTool(output="hello world")
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="read"),
            ToolCallInputDelta(call_id="c1", json_delta='{"path":"a.txt"}'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
        [
            TextDelta(text="done."),
            FinishedReason(reason="stop"),
        ],
    ]
    agent = Agent(llm=FakeLLMClient(rounds), tools=ToolRegistry([tool]))
    events = await _collect(agent, SendPrompt(text="read a.txt"), asyncio.Event())
    types = [type(e).__name__ for e in events]
    assert types == [
        "TurnStarted",
        "ToolCallStarted",
        "ToolCallFinished",
        "AssistantTextDelta",
        "AssistantMessageCompleted",
        "TurnEnded",
    ]
    assert tool.calls[0].path == "a.txt"
    # tool message + second user-less turn made it into history
    roles = [m["role"] for m in agent.history]
    assert roles == ["user", "assistant", "tool", "assistant"]


@pytest.mark.asyncio
async def test_tool_execute_error_yields_failed_and_recovers():
    class _Boom:
        id = "read"
        description = "fake"
        params = ReadParams
        async def execute(self, args, ctx):
            raise RuntimeError("disk full")
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="read"),
            ToolCallInputDelta(call_id="c1", json_delta='{"path":"a.txt"}'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
        [
            TextDelta(text="sorry"),
            FinishedReason(reason="stop"),
        ],
    ]
    agent = Agent(llm=FakeLLMClient(rounds), tools=ToolRegistry([_Boom()]))
    events = await _collect(agent, SendPrompt(text="x"), asyncio.Event())
    types = [type(e).__name__ for e in events]
    assert "ToolCallFailed" in types
    assert types[-1] == "TurnEnded"
    # tool error fed back to LLM
    tool_msg = next(m for m in agent.history if m["role"] == "tool")
    assert "disk full" in tool_msg["content"]


@pytest.mark.asyncio
async def test_unknown_tool_name_fails_gracefully():
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="no_such_tool"),
            ToolCallInputDelta(call_id="c1", json_delta='{}'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
        [
            TextDelta(text="ok"),
            FinishedReason(reason="stop"),
        ],
    ]
    agent = Agent(llm=FakeLLMClient(rounds), tools=ToolRegistry([]))
    events = await _collect(agent, SendPrompt(text="x"), asyncio.Event())
    types = [type(e).__name__ for e in events]
    assert "ToolCallFailed" in types
    assert types[-1] == "TurnEnded"


@pytest.mark.asyncio
async def test_invalid_args_json_fails_gracefully():
    tool = _FakeReadTool()
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="read"),
            ToolCallInputDelta(call_id="c1", json_delta='{not json'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
        [
            TextDelta(text="ok"),
            FinishedReason(reason="stop"),
        ],
    ]
    agent = Agent(llm=FakeLLMClient(rounds), tools=ToolRegistry([tool]))
    events = await _collect(agent, SendPrompt(text="x"), asyncio.Event())
    types = [type(e).__name__ for e in events]
    assert "ToolCallFailed" in types
    assert types[-1] == "TurnEnded"
    assert tool.calls == []  # never reached
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/domain/test_agent.py -v`
Expected: prior tests pass, 4 new fail (stub `_execute_tool_call` only emits failure).

- [ ] **Step 3: Replace `_execute_tool_call`**

In `src/poor_code/domain/agent.py`, replace the stub `_execute_tool_call` method with:

```python
    async def _execute_tool_call(
        self, turn_id: str, call: _PendingCall, ctx: ToolContext
    ) -> AsyncIterator[Event]:
        tool = self.tools.get(call.name)
        if tool is None:
            err = f"unknown tool: {call.name}"
            yield ToolCallStarted(
                turn_id=turn_id, tool_call_id=call.call_id,
                tool_name=call.name, args={},
            )
            yield ToolCallFailed(
                turn_id=turn_id, tool_call_id=call.call_id, error=err,
            )
            self.history.append({
                "role": "tool", "tool_call_id": call.call_id,
                "content": f"ERROR: {err}",
            })
            return

        try:
            args = tool.params.model_validate_json(call.args_json or "{}")
        except Exception as e:
            err = f"invalid arguments: {e}"
            yield ToolCallStarted(
                turn_id=turn_id, tool_call_id=call.call_id,
                tool_name=call.name, args={},
            )
            yield ToolCallFailed(
                turn_id=turn_id, tool_call_id=call.call_id, error=err,
            )
            self.history.append({
                "role": "tool", "tool_call_id": call.call_id,
                "content": f"ERROR: {err}",
            })
            return

        yield ToolCallStarted(
            turn_id=turn_id, tool_call_id=call.call_id,
            tool_name=call.name, args=args.model_dump(),
        )
        try:
            result = await tool.execute(args, ctx)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            yield ToolCallFailed(
                turn_id=turn_id, tool_call_id=call.call_id, error=err,
            )
            self.history.append({
                "role": "tool", "tool_call_id": call.call_id,
                "content": f"ERROR: {err}",
            })
            return

        yield ToolCallFinished(
            turn_id=turn_id, tool_call_id=call.call_id, result=result.output,
        )
        self.history.append({
            "role": "tool", "tool_call_id": call.call_id,
            "content": result.output,
        })
```

- [ ] **Step 4: Run to verify all tests pass**

Run: `uv run pytest tests/domain/test_agent.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/domain/agent.py tests/domain/test_agent.py
git commit -m "feat(agent): tool execution + error feedback to LLM"
```

---

## Task 16: Agent — max iterations + cancellation

**Files:**
- Modify: `tests/domain/test_agent.py` — add scenarios D, E

The existing `Agent.run` already implements both behaviors (the `for _ in range(MAX_ITERATIONS)` loop falls through to a final `TurnEnded`; `cancel.is_set()` is checked before each iteration and between stream events). This task is "lock in the contract" tests only.

- [ ] **Step 1: Add the failing/locking tests**

Append to `tests/domain/test_agent.py`:

```python
@pytest.mark.asyncio
async def test_max_iterations_terminates_with_turn_ended():
    """Tool-call → tool-call → ... 10 rounds scripted. Loop is capped at 8."""
    from poor_code.domain.agent import MAX_ITERATIONS

    rounds = []
    for i in range(MAX_ITERATIONS + 2):
        cid = f"c{i}"
        rounds.append([
            ProviderToolCallStarted(call_id=cid, name="read"),
            ToolCallInputDelta(call_id=cid, json_delta='{"path":"a.txt"}'),
            ToolCallEnded(call_id=cid),
            FinishedReason(reason="tool_calls"),
        ])
    tool = _FakeReadTool()
    agent = Agent(llm=FakeLLMClient(rounds), tools=ToolRegistry([tool]))
    events = await _collect(agent, SendPrompt(text="loop"), asyncio.Event())
    # Did not crash, terminated with TurnEnded after exactly MAX_ITERATIONS LLM calls
    assert events[-1].__class__.__name__ == "TurnEnded"
    assert len(agent.llm.calls) == MAX_ITERATIONS


@pytest.mark.asyncio
async def test_cancel_before_first_iteration_yields_turn_failed():
    cancel = asyncio.Event()
    cancel.set()
    agent = Agent(llm=FakeLLMClient([]), tools=ToolRegistry([]))
    events = await _collect(agent, SendPrompt(text="x"), cancel)
    types = [type(e).__name__ for e in events]
    assert types[-1] == "TurnFailed"
    assert events[-1].error == "cancelled"
```

- [ ] **Step 2: Run to verify**

Run: `uv run pytest tests/domain/test_agent.py -v`
Expected: 8 passed (the prior 6 + 2 new).

- [ ] **Step 3: Commit**

```bash
git add tests/domain/test_agent.py
git commit -m "test(agent): lock in MAX_ITERATIONS cap + early-cancel contract"
```

---

## Task 17: Delete EchoAgent + wire cli.py

**Files:**
- Delete: `src/poor_code/domain/echo_agent.py`
- Delete: `tests/domain/test_echo_agent.py`
- Modify: `src/poor_code/cli.py`

- [ ] **Step 1: Delete EchoAgent + its test**

Run: `git rm src/poor_code/domain/echo_agent.py tests/domain/test_echo_agent.py`
Expected: both files removed from the index.

- [ ] **Step 2: Rewrite cli.py**

Replace the contents of `src/poor_code/cli.py`:

```python
"""poor-code entrypoint.

Builds the real Agent (LLMClient + ToolRegistry) and hands it to the
Textual app. Fails fast at startup if OLLAMA_API_KEY is missing.
"""
from __future__ import annotations

import os
import sys

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.auth import MissingApiKey
from poor_code.provider.providers import ollama_cloud


DEFAULT_MODEL = os.environ.get("POOR_CODE_MODEL", "qwen2.5-coder:7b")


def main() -> None:
    try:
        llm = ollama_cloud.client(model=DEFAULT_MODEL)
    except MissingApiKey as e:
        print(f"error: {e}", file=sys.stderr)
        print(
            "Set OLLAMA_API_KEY in your environment, or override the model with POOR_CODE_MODEL.",
            file=sys.stderr,
        )
        sys.exit(2)

    tools = ToolRegistry([ReadTool()])
    PoorCodeApp(agent=Agent(llm=llm, tools=tools)).run()
```

- [ ] **Step 3: Smoke-check the CLI loads without OLLAMA_API_KEY**

Run: `env -u OLLAMA_API_KEY uv run python -c "from poor_code.cli import main; print('ok')"`
Expected: `ok` (imports without raising — error only fires inside `main()`).

- [ ] **Step 4: Smoke-check the CLI exits cleanly when no key**

Run: `env -u OLLAMA_API_KEY uv run poor-code </dev/null; echo "exit=$?"`
Expected: stderr shows the `OLLAMA_API_KEY` message; `exit=2`.

- [ ] **Step 5: Run full test suite (excluding migrated UI test, done next task)**

Run: `uv run pytest tests/ --ignore=tests/ui -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add -u src/poor_code/cli.py
git commit -m "feat(cli): wire real Agent (Ollama Cloud + ReadTool); remove EchoAgent"
```

---

## Task 18: Migrate UI integration tests to Agent + FakeLLMClient

**Files:**
- Modify: `tests/ui/test_app_flow.py`

The existing test injects a duck-typed `ScriptedAgent`. We keep that ergonomic shape but swap the scripted body for a real `Agent` wrapping a `FakeLLMClient`, proving the end-to-end wiring works with the new Agent.

- [ ] **Step 1: Rewrite test_app_flow.py**

Replace the contents of `tests/ui/test_app_flow.py`:

```python
import asyncio

from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import FinishedReason, TextDelta
from tests.provider.fakes import FakeLLMClient


def _agent_text(text: str) -> Agent:
    return Agent(llm=FakeLLMClient.text_only(text), tools=ToolRegistry([]))


async def test_submit_routes_through_agent_and_updates_store():
    async with PoorCodeApp(agent=_agent_text("hi there")).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("p", "i", "n", "g")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()

        state = pilot.app.store.state
        assert len(state.turns) == 1
        turn = state.turns[0]
        assert turn.user_text == "ping"
        assert turn.status == "done"
        assert turn.assistant_text == "hi there"
        assert state.is_processing is False


async def test_cancel_during_turn_marks_failed():
    """Build a FakeLLMClient that yields slowly so we can cancel mid-stream."""

    class _SlowLLM:
        async def stream(self, messages, tools):
            for _ in range(50):
                await asyncio.sleep(0.05)
                yield TextDelta(text=".")
            yield FinishedReason(reason="stop")

    agent = Agent(llm=_SlowLLM(), tools=ToolRegistry([]))
    async with PoorCodeApp(agent=agent).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(delay=0.05)
        assert pilot.app.store.state.is_processing is True
        pilot.app.action_cancel_or_quit()
        for _ in range(20):
            await pilot.pause(delay=0.05)
        state = pilot.app.store.state
        assert state.is_processing is False
        assert state.turns[0].status == "failed"
        assert state.last_error == "cancelled"
```

- [ ] **Step 2: Run UI tests**

Run: `uv run pytest tests/ui/ -v`
Expected: 2 passed.

- [ ] **Step 3: Run full suite**

Run: `uv run pytest -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/ui/test_app_flow.py
git commit -m "test(ui): migrate app-flow test to Agent + FakeLLMClient"
```

---

## Task 19: Optional live Ollama Cloud sanity test

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_ollama_cloud_live.py`

This test costs real tokens and is skipped unless `OLLAMA_API_KEY` is set. It exists to catch wiring breakage that mocks can't catch (URL, header, model id).

- [ ] **Step 1: Implement**

Create `tests/integration/__init__.py` empty. Create `tests/integration/test_ollama_cloud_live.py`:

```python
"""Live wiring test for Ollama Cloud. Skipped unless OLLAMA_API_KEY is set.
Costs a few tokens; run sparingly. Do NOT add to CI by default.
"""
import os

import pytest

from poor_code.provider.providers import ollama_cloud


pytestmark = pytest.mark.skipif(
    not os.environ.get("OLLAMA_API_KEY"),
    reason="OLLAMA_API_KEY not set",
)


@pytest.mark.asyncio
async def test_one_round_trip():
    model = os.environ.get("POOR_CODE_MODEL", "qwen2.5-coder:7b")
    llm = ollama_cloud.client(model=model)
    events = []
    async for ev in llm.stream(
        messages=[{"role": "user", "content": "say hi in one word"}],
        tools=[],
    ):
        events.append(ev)
    kinds = [type(e).__name__ for e in events]
    assert "TextDelta" in kinds
    assert kinds[-1] == "FinishedReason"
```

- [ ] **Step 2: Verify it skips without the env var**

Run: `env -u OLLAMA_API_KEY uv run pytest tests/integration/ -v`
Expected: 1 skipped.

- [ ] **Step 3: (If you have a key) Verify it passes live**

Run: `uv run pytest tests/integration/ -v`
Expected: 1 passed (or skipped if no key).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_ollama_cloud_live.py
git commit -m "test(integration): optional live Ollama Cloud round-trip"
```

---

## Self-Review (executor: verify these before finishing)

**Spec coverage map (spec section → task that implements it):**

| Spec section | Implemented in |
|---|---|
| §2 Scope — Ollama Cloud OpenAI-compat | Tasks 6, 7, 8, 9 |
| §3 Module layout | All tasks combined |
| §4 Data flow / loop | Tasks 14, 15, 16 |
| §5 Provider 4-axis | Tasks 2 (events), 3 (auth), 4 (framing), 5 (route), 6+7 (protocol), 8 (client), 9 (provider) |
| §6 Tool layer | Tasks 10, 11, 12 |
| §7 Events used | (existing in messages.py — no task needed) |
| §8 Conversation state | Task 14 (history field, accumulation test) |
| §9 Cancellation | Tasks 14, 16; Task 18 (e2e via UI test) |
| §10 Error handling | Task 15 (tool errors), Task 14 (stream exception → TurnFailed) |
| §11 Testing strategy | Tasks 4, 6, 7, 8, 12, 14, 15, 16, 18, 19 |
| §13 Implementation checklist | Tasks 1–19 |

**Spec section not covered explicitly:**

- The spec says network/5xx → `TurnFailed`. The `Agent.run` body wraps the stream in `try/except` and emits `TurnFailed`. Verify by reading Task 14's exception handler.
- The spec says missing `OLLAMA_API_KEY` raises at startup. Task 17 catches `MissingApiKey` and `sys.exit(2)`. Verified by Task 17 step 4.

**Type / name consistency checks:**

- `ToolCallStarted` / `ToolCallFinished` / `ToolCallFailed` event names match `messages.py` (existing). Plan calls them exactly that throughout.
- `OpenAIChat.for_stream()` is used in `LLMClient.stream()` to get fresh per-stream parser state (Task 7 + Task 8 alignment).
- `Tool.params` is `type[BaseModel]`; registry calls `t.params.model_json_schema()` (Task 11) — matches `Tool` Protocol (Task 10).
- `ToolContext` constructor positional vs keyword: tests use keyword args throughout; dataclass supports both. OK.
- Agent constructor signature `Agent(llm=..., tools=...)` is consistent across Tasks 14, 17, 18.

**Placeholder scan:** none — every step has full code or full command.

**Granularity:** each step is one action under ~5 minutes; longer ones broken across steps.
