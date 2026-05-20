# UI App Architecture Design

- **Date**: 2026-05-20
- **Status**: design (no implementation yet beyond welcome screen)
- **Scope**: UI layer + UI↔domain boundary contract. Domain internals are sketched, not implemented.
- **Related**: `docs/poor-code-philosophy`

## Context

poor-code is a TUI coding agent (Python 3.14 + Textual). The first session built a welcome screen with a minimal package skeleton (`src/poor_code/{app,cli,screens,widgets,styles}`). This design fixes the load-bearing architectural decisions *before* features start landing, so the structure compensates for a weak LLM rather than getting overwritten ad hoc.

The repo philosophy doc (`docs/poor-code-philosophy`) is a *research lens* (9-layer deterministic pipeline). The first-class abstractions of the **actual code** are: **Provider · Tool · SlashCommand · Hook · Profile**. The 9-layer pipeline lives *inside* tool implementations and hooks, not as folders.

## Constraints

- **Framework-free**. No LangChain / LangGraph. Standard library + Textual + `httpx` for vendor SDKs. Rationale separately in §0.
- **Weak-model target**. Local Gemma-class models. Tool output curation and hook-based context management are 1급 features — they cannot live behind a framework's abstractions.
- **Don't translate the philosophy doc into folders**. 9-layer pipeline stays as a research lens, not directory names. (See memory: `feedback_dont_overfit_to_docs.md`.)
- **TUI = Textual**. Idiomatic Textual where it doesn't conflict with the boundary.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | UI state lives in a **single immutable `AppState`** + reducer. Widget-local `reactive` is reserved for *purely UI-local* state (input box value, scroll position). | Backend-dev friendly mental model: in-memory event-sourcing projection. Replay/snapshot/test trivially. |
| D2 | UI↔domain boundary shape = **Command in / Event out** (CQRS-ish). | UI sends `SendPrompt`/`CancelTurn`/`RunSlashCommand`. Domain emits `TurnStarted`/`AssistantTextDelta`/`ToolCall*`/etc. Hooks observe Events naturally. |
| D3 | Folder layout = **layered** (`ui/` + `domain/` + `infra/`), plus a single contract file `messages.py` at the root. | Layered is familiar; the contract file anchors the boundary as a *type*, not a folder. |
| D4 | The 9-layer pipeline is **not** a folder structure. `domain/{agent, provider, tool, hook, slash_command, profile}.py` are the 5 first-class abstractions; pipeline concerns map into tools and hooks. | Memory feedback (`feedback_dont_overfit_to_docs.md`). |
| D5 | **No `bus.py`**. Cross-cutting in-domain = `HookBus`. Domain→UI broadcast = `Agent.run` async generator yield. Two channels are enough. | YAGNI. Removed from §1. |
| D6 | Loop = `async def Agent.run(cmd, cancel) -> AsyncIterator[Event]`. One `Agent` instance per conversation; turn state persists on the instance. | Matches claude-code's `QueryEngine.submitMessage` (`src/QueryEngine.ts:209`). |
| D7 | Reducer is pure. Store dispatches actions = `Event | UIAction`. **Commands never enter the reducer** — they go from `App.submit()` straight to `Agent.run()`. Optimistic UI updates use `UIAction`. | Keeps reducer testable without domain. UI knows it intends to send a command; the optimistic state is a UI concern. |
| D8 | Strict import rules. `domain/` cannot import `ui/`, `textual`, or `infra/`. `ui/` cannot import `infra/`. `messages.py` is importable from anywhere and depends only on the standard library. | Boundary is enforceable, not aspirational. Lint rule recommended (e.g., `import-linter`). |

## §0 — Why no framework

For poor-code specifically:

- LangChain's value (Provider adapters, message types, tool decorator) can be reproduced in ~50 lines per backend; we'd otherwise inherit Pydantic v2 + langchain-core + langchain + per-provider packages.
- LangGraph's value (state machine, checkpointer, streaming) collides with our immutable `AppState` + reducer pattern. Adopting it costs us our state design.
- Neither framework gives us what poor-code actually needs: tool *output curation*, hook-based context pruning, profile-specific configuration. Those are still on us.
- Reconsider when: multi-agent orchestration becomes 1급, or session persistence/replay becomes a user-facing feature.

## §1 — Folder Layout

```
src/poor_code/
├── __init__.py
├── __main__.py
├── cli.py
├── app.py                       # PoorCodeApp (Textual root)
│
├── messages.py                  # ★ Command + Event dataclasses (the contract)
│
├── ui/                          # Textual-touching code only
│   ├── __init__.py
│   ├── store.py                 # AppState + dispatch + reducer + UIAction
│   ├── bindings.py              # OPTIONAL — bridge code lives in app.py by default;
│   │                            #   extract here only if app.py grows past ~150 LOC
│   ├── screens/
│   │   ├── __init__.py
│   │   └── welcome.py
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── banner.py
│   │   └── prompt_box.py
│   └── styles/
│       └── app.tcss
│
├── domain/                      # UI-free, vendor-SDK-free
│   ├── __init__.py
│   ├── agent.py                 # Agent class + inner loop
│   ├── provider.py              # Provider Protocol + ProviderResponse + ToolSpec + AssistantMessage
│   ├── tool.py                  # Tool Protocol + ToolRegistry
│   ├── slash_command.py         # SlashCommand Protocol + SlashCommandRegistry
│   ├── hook.py                  # Hook Protocol + HookContext + HookBus
│   └── profile.py               # Profile dataclass (bundles the 5)
│
└── infra/                       # External I/O (filesystem, http providers, MCP, ...)
    └── __init__.py              # Populated when first adapter lands
```

Tests:
```
tests/
├── test_store.py                # Pure reducer tests, no Textual
├── test_messages.py             # Dataclass roundtrip / contract
└── ui/test_welcome.py           # Textual App.run_test()
```

**What exists now** (already created in session 1): the UI shell (app, cli, screens/welcome, widgets/banner+prompt_box, styles).
**What this design adds**: `messages.py`, `ui/store.py`, `ui/bindings.py`, empty `domain/__init__.py`, empty `infra/__init__.py`.
**Deferred until the first domain feature**: contents of `domain/{agent,provider,tool,hook,slash_command,profile}.py`. Their signatures are defined in this doc; their *bodies* are written when they have a concrete first caller.

## §2 — `messages.py` Contract

Pure dataclasses, no behavior. The whole contract between UI and domain. `_new_id` below is a module-private helper: `_new_id = lambda: uuid.uuid4().hex`.

### Commands (UI → domain)

```python
@dataclass(frozen=True)
class Command:
    """Marker base."""

@dataclass(frozen=True)
class SendPrompt(Command):
    text: str
    cmd_id: str = field(default_factory=_new_id)

@dataclass(frozen=True)
class CancelTurn(Command):
    cmd_id: str = field(default_factory=_new_id)

@dataclass(frozen=True)
class RunSlashCommand(Command):
    name: str
    args: tuple[str, ...] = ()
    cmd_id: str = field(default_factory=_new_id)
```

### Events (domain → UI)

```python
@dataclass(frozen=True)
class Event:
    """Marker base."""

# Lifecycle
@dataclass(frozen=True)
class TurnStarted(Event):
    cmd_id: str
    turn_id: str = field(default_factory=_new_id)

@dataclass(frozen=True)
class TurnEnded(Event):
    turn_id: str

@dataclass(frozen=True)
class TurnFailed(Event):
    turn_id: str
    error: str

# Streaming output
@dataclass(frozen=True)
class AssistantTextDelta(Event):
    turn_id: str
    text: str                       # chunk only, not cumulative

@dataclass(frozen=True)
class AssistantMessageCompleted(Event):
    turn_id: str
    text: str

# Tool calls
@dataclass(frozen=True)
class ToolCallStarted(Event):
    turn_id: str
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]

@dataclass(frozen=True)
class ToolCallFinished(Event):
    turn_id: str
    tool_call_id: str
    result: Any

@dataclass(frozen=True)
class ToolCallFailed(Event):
    turn_id: str
    tool_call_id: str
    error: str

# Telemetry
@dataclass(frozen=True)
class UsageUpdated(Event):
    turn_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
```

### Design rules baked into the contract

1. **`frozen=True` everywhere**. Reducer can safely keep references.
2. **`cmd_id`/`turn_id` correlation IDs**. One user input → one Command → one turn_id → many Events.
3. **No methods on dataclasses**. Rendering and serialization live elsewhere.
4. **`Any` for tool args/result**. Tools are an open extension point; the ToolRegistry tells UI how to render.
5. **No vendor SDK types** (e.g., Anthropic `MessageParam`). Provider adapters translate vendor shapes to our types.
6. **`AssistantTextDelta.text` is the chunk, not the running total**. Reducer accumulates.

### What is *not* in `messages.py`

- UI routing (`OpenScreen(...)`) — that's a `UIAction`, not a Command.
- Progress-bar specific updates — UI derives them from existing state.
- Raw vendor messages — translated at the Provider boundary.

## §3 — Store, AppState, Reducer

### `AppState`

```python
@dataclass(frozen=True)
class ToolCallView:
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    status: Literal["running", "done", "failed"]
    result: Any | None = None
    error: str | None = None

@dataclass(frozen=True)
class TurnView:
    turn_id: str | None              # None until TurnStarted arrives (optimistic state)
    cmd_id: str
    user_text: str
    assistant_text: str = ""
    tool_calls: tuple[ToolCallView, ...] = ()
    status: Literal["pending", "running", "done", "failed"] = "pending"
    error: str | None = None

@dataclass(frozen=True)
class UsageState:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

@dataclass(frozen=True)
class AppState:
    turns: tuple[TurnView, ...] = ()
    is_processing: bool = False
    usage: UsageState = field(default_factory=UsageState)
    last_error: str | None = None
    cwd: str = ""
```

### `UIAction` — UI-only signals (separate from Event)

```python
@dataclass(frozen=True)
class UIAction:
    """Marker base. Defined in ui/store.py; domain cannot import."""

@dataclass(frozen=True)
class PromptSubmitted(UIAction):
    cmd_id: str
    user_text: str

@dataclass(frozen=True)
class CwdChanged(UIAction):
    cwd: str

Action = Event | UIAction
```

### Reducer (pure function)

```python
def reduce(state: AppState, action: Action) -> AppState:
    match action:
        case PromptSubmitted(cmd_id=cid, user_text=text):
            new_turn = TurnView(turn_id=None, cmd_id=cid, user_text=text, status="pending")
            return replace(state, turns=state.turns + (new_turn,), is_processing=True)

        case TurnStarted(cmd_id=cid, turn_id=tid):
            return _update_turn_by_cmd(state, cid, turn_id=tid, status="running")

        case AssistantTextDelta(turn_id=tid, text=chunk):
            return _update_turn_by_turn(
                state, tid,
                assistant_text=_get_turn(state, tid).assistant_text + chunk,
            )

        case ToolCallStarted(turn_id=tid, tool_call_id=cid, tool_name=n, args=a):
            return _append_tool_call(state, tid, ToolCallView(cid, n, a, "running"))

        case ToolCallFinished(turn_id=tid, tool_call_id=cid, result=r):
            return _update_tool_call(state, tid, cid, status="done", result=r)

        case ToolCallFailed(turn_id=tid, tool_call_id=cid, error=e):
            return _update_tool_call(state, tid, cid, status="failed", error=e)

        case TurnEnded(turn_id=tid):
            return replace(_update_turn_by_turn(state, tid, status="done"),
                           is_processing=False)

        case TurnFailed(turn_id=tid, error=e):
            return replace(_update_turn_by_turn(state, tid, status="failed", error=e),
                           is_processing=False, last_error=e)

        case UsageUpdated(input_tokens=i, output_tokens=o, cost_usd=c):
            return replace(state, usage=UsageState(
                input_tokens=state.usage.input_tokens + i,
                output_tokens=state.usage.output_tokens + o,
                cost_usd=state.usage.cost_usd + c,
            ))

        case CwdChanged(cwd=cwd):
            return replace(state, cwd=cwd)

        case _:
            return state
```

### `Store`

```python
class Store:
    """In-memory event-sourced projection. Single-threaded asyncio loop."""

    def __init__(self, initial: AppState):
        self._state = initial
        self._listeners: list[Callable[[AppState], None]] = []

    @property
    def state(self) -> AppState: return self._state

    def dispatch(self, action: Action) -> None:
        new = reduce(self._state, action)
        if new is self._state:
            return
        self._state = new
        for listener in self._listeners:
            listener(new)

    def subscribe(self, listener: Callable[[AppState], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)
```

Commands do not flow through the reducer. `App.submit()` (next section) dispatches `PromptSubmitted` *and* hands the Command to `Agent.run()`. Optimistic update and side effect are siblings, not nested.

## §4 — UI ↔ Store Binding

### App = store + agent + cancel owner

```python
class PoorCodeApp(App):
    CSS_PATH = "ui/styles/app.tcss"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "cancel_or_quit", "Cancel/Quit"),
    ]

    # Bridge: store update → reactive → widget watchers
    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def __init__(self) -> None:
        super().__init__()
        self.store = Store(AppState(cwd=str(Path.cwd())))
        self.agent: Agent | None = None         # injected at startup (§5)
        self._cancel = asyncio.Event()

    def on_mount(self) -> None:
        self.store.subscribe(lambda s: setattr(self, "app_state", s))
        self.app_state = self.store.state
        self.push_screen(WelcomeScreen())

    def submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        cmd = self._route(text)
        self.store.dispatch(PromptSubmitted(cmd_id=cmd.cmd_id, user_text=text))
        self._cancel = asyncio.Event()
        self.run_worker(self._run_turn(cmd), group="turn", exclusive=True)

    def _route(self, text: str) -> Command:
        if text.startswith("/"):
            name, *args = text[1:].split()
            return RunSlashCommand(name=name, args=tuple(args))
        return SendPrompt(text)

    async def _run_turn(self, cmd: Command) -> None:
        async for event in self.agent.run(cmd, self._cancel):
            self.store.dispatch(event)

    def action_cancel_or_quit(self) -> None:
        if self.app_state.is_processing:
            self._cancel.set()
        else:
            self.exit()
```

Key choices:

- **`run_worker(..., group="turn", exclusive=True)`** — Textual's worker manager. Auto-cancels previous turn in the same group; auto-cleans on app exit.
- **`_cancel` reset per turn** — prevents prior-turn signals from killing a fresh turn.
- **`submit()` is the only public entry point**. Widgets call `self.app.submit(text)`; PromptBox does not know about Commands.
- **Routing centralized in `_route()`** — `/`-prefix detection is not a widget concern.

### Widget: subscribe to `app_state`

```python
class ChatLog(Widget):
    def on_mount(self):
        self.watch(self.app, "app_state", self._render)

    def _render(self, state: AppState) -> None:
        # Naive render; replace with diff-aware update once volume requires it.
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.remove_children()
        for turn in state.turns:
            scroll.mount(Static(f"> {turn.user_text}", classes="user"))
            if turn.assistant_text:
                scroll.mount(Static(turn.assistant_text, classes="assistant"))
            for tc in turn.tool_calls:
                scroll.mount(Static(f"  ↳ {tc.tool_name}({tc.status})", classes="tool"))
```

### Widget → App input

```python
class PromptBox(Container):
    def compose(self):
        yield Input(placeholder="...", id="prompt-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one(Input).value = ""
        self.app.submit(event.value)
```

### Screen vs single-screen

For v0: one ChatScreen that renders welcome content when `state.turns` is empty, then chat once turns exist. WelcomeScreen as a separate route stays only if welcome-specific behavior (onboarding) is added later.

## §5 — Domain Internals

### `Agent`

```python
class Agent:
    def __init__(self, profile: Profile, provider: Provider):
        self.profile = profile
        self.provider = provider
        self._archive: list[dict] = []          # raw conversation; for UI/log/persistence
        # The LLM-bound view is computed each turn by the pre_sample hook.
        # _archive is the source of truth; hooks return derived views, never mutate.

    async def run(self, cmd: Command, cancel: asyncio.Event) -> AsyncIterator[Event]:
        match cmd:
            case SendPrompt(text=t, cmd_id=cid):
                async for ev in self._prompt_turn(cid, t, cancel):
                    yield ev
            case RunSlashCommand(name=n, args=a, cmd_id=cid):
                async for ev in self._slash_turn(cid, n, a, cancel):
                    yield ev
            case CancelTurn():
                cancel.set()
```

### Inner loop: sample → tools → re-sample

```python
async def _prompt_turn(self, cmd_id, text, cancel):
    turn_id = _new_id()
    yield TurnStarted(cmd_id=cmd_id, turn_id=turn_id)
    self._archive.append({"role": "user", "content": text})

    try:
        while True:
            if cancel.is_set():
                raise asyncio.CancelledError

            # ① pre_sample hook: produce LLM-bound view from archive
            ctx = await self.profile.hooks.fire(
                "pre_sample", HookContext(messages=list(self._archive)))

            # ② sample
            resp = await self.provider.complete(
                messages=ctx.messages,
                tools=self.profile.tools.specs(),
                **self.profile.sample_params,
            )

            # ③ stream tokens
            async for delta in resp.text_stream:
                yield AssistantTextDelta(turn_id=turn_id, text=delta)
                if cancel.is_set():
                    resp.abort()
                    raise asyncio.CancelledError

            final = await resp.final()
            yield AssistantMessageCompleted(turn_id=turn_id, text=final.text)
            yield UsageUpdated(turn_id=turn_id, **resp.usage)
            self._archive.append(final.to_message())

            # ④ no tool calls → done
            if not final.tool_calls:
                yield TurnEnded(turn_id=turn_id)
                return

            # ⑤ tool calls (sequential v0)
            for tc in final.tool_calls:
                yield ToolCallStarted(turn_id, tc.id, tc.name, tc.args)
                await self.profile.hooks.fire("pre_tool", HookContext(tool_call=tc))
                tool = self.profile.tools.get(tc.name)
                try:
                    raw = await tool.run(tc.args, cancel=cancel)
                    refined = await self.profile.hooks.fire(
                        "post_tool", HookContext(tool_call=tc, result=raw))
                    yield ToolCallFinished(turn_id, tc.id, refined.result)
                    self._archive.append({"role": "tool", "tool_call_id": tc.id,
                                          "content": refined.result})
                except Exception as e:
                    yield ToolCallFailed(turn_id, tc.id, str(e))
                    await self.profile.hooks.fire("tool_failed",
                                                  HookContext(tool_call=tc, error=e))
                    self._archive.append({"role": "tool", "tool_call_id": tc.id,
                                          "content": f"error: {e}"})
            # ⑥ loop back to sample with tool results

    except asyncio.CancelledError:
        yield TurnFailed(turn_id=turn_id, error="cancelled")
```

### `Provider` Protocol

```python
class Provider(Protocol):
    name: str
    async def complete(
        self, messages: list[dict], tools: list[ToolSpec], **params
    ) -> "ProviderResponse": ...

class ProviderResponse(Protocol):
    text_stream: AsyncIterator[str]
    # usage keys match UsageUpdated's fields exactly so `UsageUpdated(**resp.usage)` works:
    #   {"input_tokens": int, "output_tokens": int, "cost_usd": float}
    # Provider adapters compute cost_usd locally (per-provider pricing table).
    usage: dict
    async def final(self) -> "AssistantMessage": ...
    def abort(self) -> None: ...

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict                            # JSON schema

@dataclass(frozen=True)
class AssistantMessage:
    text: str
    tool_calls: tuple["ToolCall", ...]
    def to_message(self) -> dict: ...

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict
```

Vendor SDK adapters live in `infra/` (e.g., `infra/anthropic_provider.py`, `infra/ollama_provider.py`).

### `Tool` + `ToolRegistry`

```python
class Tool(Protocol):
    name: str
    description: str
    args_schema: dict
    async def run(self, args: dict, cancel: asyncio.Event) -> Any: ...

class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()):
        self._tools = {t.name: t for t in tools}
    def get(self, name: str) -> Tool: return self._tools[name]
    def register(self, tool: Tool) -> None: self._tools[tool.name] = tool
    def specs(self) -> list[ToolSpec]:
        return [ToolSpec(t.name, t.description, t.args_schema) for t in self._tools.values()]
```

`register()` makes MCP integration trivial: an MCP client adapter (in `infra/`) lists tools from servers and calls `tools.register(adapted_tool)`. Domain core unchanged.

### `Hook` + `HookContext` + `HookBus`

```python
@dataclass
class HookContext:
    messages: list[dict] | None = None
    tool_call: ToolCall | None = None
    result: Any = None
    error: Exception | None = None
    extras: dict[str, Any] = field(default_factory=dict)  # escape hatch

HookName = Literal["pre_sample", "pre_tool", "post_tool", "tool_failed"]

class Hook(Protocol):
    event: HookName
    async def __call__(self, ctx: HookContext) -> HookContext: ...

class HookBus:
    def __init__(self, hooks: Iterable[Hook] = ()):
        self._by_event = defaultdict(list)
        for h in hooks:
            self._by_event[h.event].append(h)

    async def fire(self, event: HookName, ctx: HookContext) -> HookContext:
        for h in self._by_event[event]:
            ctx = await h(ctx)
        return ctx
```

The four hook points correspond to philosophy doc concerns:
- `pre_sample` → Context Manager (prune/fold/summarize messages before LLM call). **Solves conversation-length growth.**
- `post_tool` → Tool output refinement (read → symbol-only fold, find → LSP-aware filter). poor-code's main IP.
- `tool_failed` → Failure Memory recording. Next turn's `pre_sample` hook injects the hint.
- `pre_tool` → Permission / confirmation.

Adding a 5th hook point requires a domain code change (Agent.run must `fire(...)`). That is intentional — hook *registration* is plugin-author territory; hook *points* are domain-design territory.

### `Profile`

```python
@dataclass(frozen=True)
class Profile:
    name: str
    tools: ToolRegistry
    hooks: HookBus
    slash_commands: "SlashCommandRegistry"
    sample_params: dict
    system_prompt: str
```

Profiles capture model-class-specific configuration. Examples envisioned:
- `anthropic_haiku`: full toolset, light post_tool refinement.
- `local_gemma_27b`: smaller toolset, heavy post_tool refinement, aggressive pre_sample pruning.

### `SlashCommand` — unified shape with Agent

```python
class SlashCommand(Protocol):
    name: str
    description: str
    async def run(
        self, args: tuple[str, ...], agent: "Agent", cancel: asyncio.Event
    ) -> AsyncIterator[Event]: ...

class SlashCommandRegistry:
    # same shape as ToolRegistry
    ...
```

Simple commands (`/help`) yield one or two events. Complex commands (`/compact`) may run an internal sample and rewrite `agent._archive`.

`_slash_turn` is a thin wrapper:

```python
async def _slash_turn(self, cmd_id, name, args, cancel):
    cmd = self.profile.slash_commands.get(name)
    if cmd is None:
        yield TurnFailed(turn_id="-", error=f"unknown command: /{name}")
        return
    turn_id = _new_id()
    yield TurnStarted(cmd_id=cmd_id, turn_id=turn_id)
    try:
        async for ev in cmd.run(args, agent=self, cancel=cancel):
            yield ev
        yield TurnEnded(turn_id=turn_id)
    except Exception as e:
        yield TurnFailed(turn_id=turn_id, error=str(e))
```

## Extension Points (what each future feature touches)

| Feature | Files changed | Domain core change? |
|---|---|---|
| New Provider (Ollama, vLLM) | `infra/<name>_provider.py` implementing `Provider` Protocol | No |
| New Tool (read, edit, bash) | `domain/tools/<name>.py` or `tools/` impl module + Profile registration | No |
| New SlashCommand (`/help`, `/compact`) | `domain/commands/<name>.py` + Profile registration | No |
| New Hook function (any of the 4 events) | hook impl + Profile registration | No |
| **New hook point** (5th event) | `domain/hook.py` (extend `HookName`) + Agent.run (add `fire`) | **Yes** |
| MCP integration | `infra/mcp_client.py` calling `ToolRegistry.register()` | No |
| **SubAgent (flat — result-only)** | New tool that constructs a fresh `Agent` and summarizes events into a result | No |
| **SubAgent (nested progress UI)** | New wrapping events (`SubAgentEvent(parent_turn_id, inner)`), `TurnView.sub_turns` tree, reducer extension, indented rendering | **Yes — v2+** |
| New screen | `ui/screens/<name>.py` + `app.push_screen()` site | No |
| New widget | `ui/widgets/<name>.py` | No |

## Test strategy (compact)

- **`tests/test_messages.py`**: dataclass equality, correlation-id propagation, immutability.
- **`tests/test_store.py`**: reducer is a pure function; one parametrized case per action. No Textual, no asyncio.
- **`tests/test_agent.py`** (later): inject a fake `Provider` that yields canned `ProviderResponse`. Assert event sequence. No real LLM.
- **`tests/ui/test_welcome.py`**: Textual `App.run_test()` smoke. Confirms widgets mount; not layout-pixel-perfect.
- **End-to-end**: a `FakeProvider` + scripted prompts + `App.run_test()` driving `submit()`. Asserts AppState snapshot.

## Out of Scope (deferred)

- Parallel tool execution (Agent.run is sequential in v0).
- Permission / confirmation UX (hook point exists; UI flow undesigned).
- Conversation persistence (`_archive` is in-memory only).
- Time-travel debugger (AppState is immutable, so this is *cheap to add later* — not done now).
- Multi-store / multi-tenant.
- SubAgent with nested progress UI (flat result-only path is supported).
- Theming / customization (single `app.tcss` for v0).

## References

- `docs/poor-code-philosophy` — research lens.
- Memory: `project_philosophy.md`, `project_stack.md`, `feedback_dont_overfit_to_docs.md`, `user_role.md`.
- claude-code cross-checks performed during design:
  - `src/QueryEngine.ts:184` `class QueryEngine` — engine-per-conversation pattern.
  - `src/query.ts:219` `export async function* query` — async generator loop.
  - `src/tasks/LocalMainSessionTask.ts:383` — `for await (const event of query(...))` consumer pattern.
  - `src/state/store.ts` — pub/sub store shape.
- Intentional divergences from claude-code: strict immutable AppState + reducer (vs their mutable `setState`); domain stays oblivious to UI store (vs their `setAppState` DI); thin `App` (vs 4683-line `main.tsx`).
