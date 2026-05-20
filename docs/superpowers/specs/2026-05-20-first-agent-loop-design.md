# First Agent Loop — Design

**Date:** 2026-05-20
**Status:** Approved (pending implementation plan)
**Supersedes:** EchoAgent v0 wiring

## 1. Goal

Replace `EchoAgent` with a real agent loop that calls an LLM, executes tools, and feeds tool results back until the model produces a final assistant message. Existing UI / Store / Event plumbing is preserved — only the `domain/` and a new `provider/` layer change.

This is the smallest unit that exercises poor-code's two top-level abstractions: **Agent + Tools**. The 9-layer pipeline from `docs/poor-code-philosophy.md` is research lens, not a folder layout — none of it appears in this spec.

## 2. Scope

In scope:

- Provider abstraction laid out as opencode's 4-axis decomposition (Protocol / Endpoint / Auth / Framing) — *structure* for all five, *implementation* for OpenAI Chat only.
- One concrete provider: **Ollama Cloud**, via the OpenAI Chat-compatible endpoint, Bearer auth (`OLLAMA_API_KEY`).
- Tool abstraction mirrored from opencode (`id`, `description`, `params` as pydantic model, `execute(args, ctx) -> ExecuteResult`).
- One concrete tool: **read** (single-file read with line range).
- Real agent loop with cancellation, max-iterations guard, tool-call error feedback.

Out of scope (explicit non-goals — do not add):

- Other providers (Anthropic, Gemini, Bedrock). The 4-axis structure must accommodate them without rework, but no code for them ships here.
- Other tools (write, bash, ls, grep, edit, ...). One tool is enough to validate the loop and the Tool interface.
- Slash command behavior (the router already exists in `app.py`; slash commands still echo through the agent).
- Permission UI / rule engine. Interface is stubbed (`ask` always returns `"allow"`).
- Plugin/Hook system.
- MCP integration.
- Token / cost tracking.
- Conversation operations: `/clear`, `/compact`, summarization.
- poor-code's 9-layer pipeline (Locator, Orchestrator, Validator, Failure Memory, ...).

## 3. Module Layout

```
src/poor_code/
├── domain/
│   ├── agent.py              ← REWRITE: single Agent class (no Protocol, no EchoAgent)
│   └── tool/                 ← NEW
│       ├── __init__.py
│       ├── base.py           ← Tool Protocol, ToolContext, ExecuteResult, PermissionRequest
│       ├── registry.py       ← ToolRegistry (name → Tool)
│       └── read.py           ← ReadTool
├── provider/                 ← NEW (opencode 4-axis)
│   ├── __init__.py
│   ├── route.py              ← Route dataclass (protocol, endpoint, auth, framing)
│   ├── auth.py               ← Auth Protocol + BearerAuth
│   ├── framing.py            ← Framing Protocol + SseFraming
│   ├── events.py             ← LLMEvent union (provider-neutral)
│   ├── client.py             ← LLMClient (assembles Route + httpx.AsyncClient, exposes stream())
│   ├── protocols/
│   │   ├── __init__.py
│   │   └── openai_chat.py    ← Protocol implementation
│   └── providers/
│       ├── __init__.py
│       └── ollama_cloud.py   ← thin wrapper: route + defaults
├── messages.py               ← UPDATE: add tool-related Events
├── cli.py                    ← UPDATE: wire real Agent(LLMClient) instead of EchoAgent
└── app.py                    ← unchanged

DELETE:
  src/poor_code/domain/echo_agent.py
  tests/domain/test_echo_agent.py
```

Why no `Agent` Protocol: substitution happens at the **LLMClient** boundary (Fake vs real), not at the Agent boundary. The Protocol was the wrong seam.

## 4. Data Flow

```
PromptBox.submit(text)
  → app.submit(text) → Store.dispatch(PromptSubmitted)
                     → run_worker(_run_turn(cmd))
                        │
                        ▼
                 Agent.run(cmd, cancel):
                   self.history.append(user_msg)
                   yield TurnStarted
                   ctx = ToolContext(turn_id=turn_id, cancel=cancel,
                                     cwd=Path.cwd(), ask=allow_all_stub)
                   for iteration in range(MAX_ITERATIONS):
                     if cancel.is_set(): yield TurnFailed("cancelled"); return
                     stream = llm.stream(self.history, tools=registry.schemas())
                     # accumulate one assistant message from stream
                     async for ev in stream:
                       match ev:
                         TextDelta         → yield AssistantTextDelta; buffer text
                         ToolCallStarted   → buffer call (id, name)
                         ToolCallInputDelta → buffer args_json
                         ToolCallEnded     → finalize call
                         FinishedReason    → break inner
                     assistant_msg = {role: "assistant", content: buffered_text,
                                      tool_calls: buffered_calls or None}
                     self.history.append(assistant_msg)
                     if not buffered_calls:
                       yield AssistantMessageCompleted(text=buffered_text)
                       yield TurnEnded
                       return
                     for call in buffered_calls:
                       yield ToolCallStarted(call_id, name, args_preview)
                       tool = registry.get(call.name)            # None → ToolCallFailed
                       try:
                         args = tool.params.model_validate_json(call.args_json)
                         result = await tool.execute(args, ctx)
                         yield ToolCallCompleted(call_id, title, output_preview)
                         self.history.append({role: "tool", tool_call_id: call.id,
                                              content: result.output})
                       except Exception as e:
                         yield ToolCallFailed(call_id, error=str(e))
                         self.history.append({role: "tool", tool_call_id: call.id,
                                              content: f"ERROR: {e}"})
                   # fell out of loop without natural termination
                   yield TurnEnded(reason="max_iterations")
```

`MAX_ITERATIONS = 8` (constant in `agent.py`; tunable later).

## 5. Provider Layer (4-axis)

### `provider/route.py`

```python
@dataclass(frozen=True)
class Route:
    protocol: Protocol
    endpoint: str           # e.g. "/v1/chat/completions"
    auth: Auth
    framing: Framing
```

### `provider/auth.py`

```python
class Auth(Protocol):
    def apply(self, headers: dict[str, str]) -> None: ...

@dataclass(frozen=True)
class BearerAuth:
    token: str
    @classmethod
    def from_env(cls, var: str) -> "BearerAuth":
        token = os.environ.get(var)
        if not token: raise MissingApiKey(var)
        return cls(token)
    def apply(self, headers): headers["Authorization"] = f"Bearer {self.token}"
```

### `provider/framing.py`

```python
class Framing(Protocol):
    async def frames(self, response: httpx.Response) -> AsyncIterator[bytes]: ...

class SseFraming:
    async def frames(self, response): ...  # yields each "data: ..." JSON payload
```

### `provider/protocols/openai_chat.py`

```python
class OpenAIChat:
    def build_body(self, messages, tools, model, **opts) -> dict:
        body = {"model": model, "messages": messages, "stream": True}
        if tools: body["tools"] = tools
        return body | opts

    def parse_chunk(self, chunk: dict) -> Iterable[LLMEvent]:
        # one SSE JSON chunk → 0..N LLMEvents
```

### `provider/events.py`

```python
LLMEvent =
    TextDelta(text: str)
  | ToolCallStarted(call_id: str, name: str)
  | ToolCallInputDelta(call_id: str, json_delta: str)
  | ToolCallEnded(call_id: str)
  | FinishedReason(reason: Literal["stop", "tool_calls", "length", "error"])
```

Provider-neutral. Adding Anthropic later means a new `protocols/anthropic_messages.py` that emits the same `LLMEvent` set — no change to `Agent`.

### `provider/client.py`

```python
class LLMClient:
    def __init__(self, route: Route, base_url: str, model: str): ...
    async def stream(self, messages, tools) -> AsyncIterator[LLMEvent]:
        # assemble URL/headers/body, open httpx stream,
        # iterate framing.frames(), parse via route.protocol.parse_chunk
```

### `provider/providers/ollama_cloud.py`

```python
DEFAULT_BASE_URL = "https://ollama.com"

def client(model: str, base_url: str = DEFAULT_BASE_URL) -> LLMClient:
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth.from_env("OLLAMA_API_KEY"),   # raises if missing
        framing=SseFraming(),
    )
    return LLMClient(route=route, base_url=base_url, model=model)
```

Default tool-capable model: `qwen2.5-coder:7b` (configurable). Resolved at `cli.py` time, not hardcoded inside the provider module.

## 6. Tool Layer

### `domain/tool/base.py`

```python
@runtime_checkable
class Tool(Protocol):
    id: str
    description: str
    params: type[BaseModel]
    async def execute(self, args: BaseModel, ctx: "ToolContext") -> "ExecuteResult": ...

@dataclass
class ToolContext:
    turn_id: str
    cancel: asyncio.Event
    cwd: Path
    ask: Callable[["PermissionRequest"], Awaitable[Literal["allow", "deny"]]]

@dataclass
class ExecuteResult:
    title: str
    output: str
    metadata: dict = field(default_factory=dict)

@dataclass
class PermissionRequest:
    tool_id: str
    pattern: str
    metadata: dict = field(default_factory=dict)
```

### `domain/tool/registry.py`

```python
class ToolRegistry:
    def __init__(self, tools: list[Tool]): ...
    def get(self, name: str) -> Tool | None: ...
    def schemas(self) -> list[dict]:
        # returns OpenAI-format tool list:
        # [{"type": "function",
        #   "function": {"name": id, "description": desc, "parameters": json_schema}}]
```

### `domain/tool/read.py`

```python
class ReadParams(BaseModel):
    path: str = Field(description="File path. Relative resolves against cwd.")
    start: int = Field(default=1, ge=1, description="1-indexed start line.")
    limit: int = Field(default=2000, ge=1, le=10000)

class ReadTool:
    id = "read"
    description = "Read a single text file with line numbers (cat -n format)."
    params = ReadParams

    async def execute(self, args, ctx):
        path = (ctx.cwd / args.path).resolve()
        if ctx.cwd.resolve() not in path.parents and path != ctx.cwd.resolve():
            raise PermissionError(f"path outside cwd: {args.path}")
        if not path.is_file():
            raise FileNotFoundError(args.path)
        # read lines [start, start+limit), format as "  N\tline"
        return ExecuteResult(title=str(path), output=formatted)
```

Permission for `read` first-stage: `ctx.ask` is wired but `ReadTool` doesn't call it (read-only, always safe). Interface present, no UI yet.

## 7. Events Added to `messages.py`

```python
ToolCallStarted(turn_id: str, call_id: str, name: str, args_preview: str)
ToolCallCompleted(turn_id: str, call_id: str, title: str, output_preview: str)
ToolCallFailed(turn_id: str, call_id: str, error: str)
```

Store reducer: append a single chat-log row per event. UI renders inline in `ChatLog`:

```
→ read("src/poor_code/app.py")          ✓
→ read("missing.py")                    ✗ FileNotFoundError
```

`output_preview` is truncated to ~120 chars for the log row; the full output goes into the tool message in `Agent.history`. Rich expandable display is future.

## 8. Conversation State

`Agent` holds `self.history: list[dict]` in OpenAI message format. Persists across turns within the app session. No persistence to disk. No truncation/compression. Cleared only by re-launching the app (a `/clear` command is future work).

## 9. Cancellation

- `asyncio.Event` from `App._cancel` is passed into `Agent.run` and forwarded into `ToolContext.cancel`.
- Checked before each iteration, before each tool execution, and inside the HTTP stream loop (between SSE frames).
- On cancel, `LLMClient.stream()` closes the httpx stream via context-manager exit. `Agent` yields `TurnFailed(error="cancelled")` and returns.
- In-flight tool execute calls must respect `ctx.cancel` cooperatively. `ReadTool` reads small files synchronously; cancel is checked once on entry.

## 10. Error Handling

| Failure | Yielded Event | Effect on history |
|---|---|---|
| Network / 5xx / SSE parse failure | `TurnFailed(error=...)` | Roll back the current turn's user message append? **No** — keep user message in history so retry by user is natural. |
| Tool args fail JSON / pydantic validation | `ToolCallFailed(error=...)` | Append tool message with `"ERROR: <validation msg>"` so model can retry |
| Tool execute raises | `ToolCallFailed(error=...)` | Append tool message with `"ERROR: <str(e)>"` |
| Unknown tool name from model | `ToolCallFailed(error="unknown tool: X")` | Same; model can recover |
| Max iterations | `TurnEnded(reason="max_iterations")` | History remains; user can prompt again |
| Cancel | `TurnFailed(error="cancelled")` | History remains |
| Missing `OLLAMA_API_KEY` at startup | Raised in `cli.py` before app launch | Clear stderr message |

## 11. Testing Strategy

### Unit

- `tests/domain/tool/test_read.py` — `ReadTool` against `tmp_path`: small file, line range, missing file, path outside cwd.
- `tests/provider/test_openai_chat.py` — `OpenAIChat.parse_chunk` against fixed SSE JSON fixtures → expected `LLMEvent` sequence (text-only, single tool call, two tool calls, finish reasons).
- `tests/provider/test_client.py` — `LLMClient.stream` end-to-end with a mocked `httpx.AsyncClient` (respx) emitting raw SSE bytes → asserts ordered `LLMEvent` sequence.
- `tests/domain/test_agent.py` — `Agent` with `FakeLLMClient` (scripted `LLMEvent` streams):
  - **A**: text-only → `AssistantTextDelta*`, `AssistantMessageCompleted`, `TurnEnded`.
  - **B**: one tool call → events in order; `history` contains user → assistant(with tool_calls) → tool(result) → assistant(text); `TurnEnded`.
  - **C**: tool execute raises → `ToolCallFailed` followed by a recovery assistant message → `TurnEnded`.
  - **D**: stream yields tool_calls every iteration up to `MAX_ITERATIONS` → `TurnEnded(reason="max_iterations")`.
  - **E**: cancel set mid-stream → `TurnFailed(error="cancelled")`.

### Integration

- `tests/ui/test_app_flow.py` — rewritten to inject `Agent(llm=FakeLLMClient(...))`. Reuses scenarios A and B above and asserts `ChatLog` rendering (assistant message visible, tool-call row visible).
- `tests/integration/test_ollama_cloud.py` — **optional**, gated on `OLLAMA_API_KEY`. Performs a single round-trip to confirm the live wiring works. Skipped in CI by default.

### Fixtures

- `FakeLLMClient` lives in `tests/provider/fakes.py`. Constructor takes either a static list of `LLMEvent` or an iterable factory keyed on round number (for multi-iteration scenarios).

## 12. Open Questions (resolved)

| Question | Decision |
|---|---|
| Provider abstraction shape | opencode's 4-axis (Protocol / Endpoint / Auth / Framing) |
| First backend | Ollama Cloud, OpenAI-compatible endpoint, Bearer auth |
| First tool | `read` |
| Tool framework | opencode-mirror: `Tool` Protocol + pydantic params + `ToolContext` + `ExecuteResult` |
| Agent Protocol? | Removed. Single `Agent` class. Substitution is at LLMClient. |
| EchoAgent? | Deleted. FakeLLMClient + Agent covers the same test scenarios. |
| Conversation state | In-memory per app session, no persistence, no truncation |
| Permission for read | Stub (`ask` returns `"allow"`); ReadTool doesn't call it |
| Multi-tool | Out of scope |
| Multi-provider | Structure ready, no implementation |

## 13. Implementation Checklist (rough)

Detailed plan deferred to writing-plans skill. High-level order:

1. `provider/` package + `OpenAIChat` protocol + `LLMClient` + `BearerAuth` + `SseFraming` — with unit tests.
2. `provider/providers/ollama_cloud.py` thin wrapper.
3. `domain/tool/` base types + `ToolRegistry` + `ReadTool` — with unit tests.
4. `messages.py` new Events.
5. Rewrite `domain/agent.py` as `Agent` class with the loop; delete `echo_agent.py`.
6. Wire `cli.py` to construct `Agent(llm=ollama_cloud.client(model))` with tool registry.
7. Update `ChatLog` reducer/rendering for the three new Events.
8. Migrate `test_app_flow.py` to FakeLLMClient.
9. Optional live test gated on `OLLAMA_API_KEY`.
