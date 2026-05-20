# UI App Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the UI↔domain boundary, single immutable AppState + reducer + Store, Textual reactive bridge, and a minimal demo loop (EchoAgent) so `uv run poor-code` shows a working request→response cycle. Domain interior (real Provider/Tool/Hook/Profile) is deferred per spec.

**Architecture:** Layered (`ui/` + `domain/` + `infra/`) with `messages.py` as the contract file at the root. UI dispatches `Command` to a single `Agent.run()` async generator and dispatches the yielded `Event` stream into a pure-function reducer. `App.app_state: reactive[AppState]` bridges the Store to Textual's watcher system. Strict import direction: `domain/` never imports `ui/`, `textual`, or `infra/`.

**Tech Stack:** Python 3.14, Textual 8.2.7+, uv, pytest, pytest-asyncio, dataclasses, asyncio. No LangChain/LangGraph (see spec §0).

**Spec:** `docs/superpowers/specs/2026-05-20-ui-app-architecture-design.md`

---

## File Structure

### Will be created

- `src/poor_code/messages.py` — Command + Event dataclasses (the contract)
- `src/poor_code/ui/__init__.py` — empty
- `src/poor_code/ui/store.py` — AppState + view dataclasses + UIAction + reducer + Store class
- `src/poor_code/ui/screens/__init__.py` — moved
- `src/poor_code/ui/screens/welcome.py` — moved + extended to host ChatLog
- `src/poor_code/ui/widgets/__init__.py` — moved
- `src/poor_code/ui/widgets/banner.py` — moved
- `src/poor_code/ui/widgets/prompt_box.py` — moved + `on_input_submitted` calls `app.submit()`
- `src/poor_code/ui/widgets/chat_log.py` — new, renders `state.turns`
- `src/poor_code/ui/styles/app.tcss` — moved
- `src/poor_code/domain/__init__.py` — empty
- `src/poor_code/domain/agent.py` — `Agent` Protocol only (no impl)
- `src/poor_code/domain/echo_agent.py` — demo `EchoAgent` (production code; wired in by `cli.py`)
- `src/poor_code/infra/__init__.py` — empty
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_messages.py`
- `tests/ui/__init__.py`
- `tests/ui/test_store.py`
- `tests/ui/test_app_flow.py` — e2e (`App.run_test()` + scripted `FakeAgent`)
- `tests/fakes.py` — `FakeAgent` test double

### Will be modified

- `src/poor_code/__init__.py` — no change needed
- `src/poor_code/app.py` — add Store, `app_state` reactive, `submit()`, `_route()`, `_run_turn()`, `action_cancel_or_quit()`, agent injection via `__init__`
- `src/poor_code/cli.py` — build EchoAgent, inject into `PoorCodeApp`
- `pyproject.toml` — add pytest + pytest-asyncio dev deps, configure pytest-asyncio mode

### Will be deleted (moved)

- `src/poor_code/screens/` — moved to `ui/screens/`
- `src/poor_code/widgets/` — moved to `ui/widgets/`
- `src/poor_code/styles/` — moved to `ui/styles/`

---

## Task 1: Add test dependencies and test scaffold

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/ui/__init__.py`

- [ ] **Step 1: Add pytest deps to dev group**

Edit `pyproject.toml`. Replace the existing `[dependency-groups]` block:

```toml
[dependency-groups]
dev = [
    "textual-dev>=1.8.0",
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]
```

- [ ] **Step 2: Add pytest config**

Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Create test package files**

Create `tests/__init__.py` (empty).
Create `tests/ui/__init__.py` (empty).
Create `tests/conftest.py` (empty — placeholder; fixtures will be added when needed).

- [ ] **Step 4: Sync and verify pytest runs**

Run: `uv sync && uv run pytest --collect-only`
Expected: `no tests collected` (no error, just empty collection)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/conftest.py tests/ui/__init__.py
git commit -m "test: add pytest + pytest-asyncio dev deps and test scaffold"
```

---

## Task 2: Refactor scaffold into `ui/` layout

**Files:**
- Move: `src/poor_code/screens/` → `src/poor_code/ui/screens/`
- Move: `src/poor_code/widgets/` → `src/poor_code/ui/widgets/`
- Move: `src/poor_code/styles/` → `src/poor_code/ui/styles/`
- Create: `src/poor_code/ui/__init__.py`
- Modify: `src/poor_code/app.py` (CSS_PATH + import paths)
- Modify: `src/poor_code/ui/screens/welcome.py` (import paths after move)

- [ ] **Step 1: Create `ui/` package and move children**

Run (from repo root):

```bash
mkdir -p src/poor_code/ui
touch src/poor_code/ui/__init__.py
git mv src/poor_code/screens src/poor_code/ui/screens
git mv src/poor_code/widgets src/poor_code/ui/widgets
git mv src/poor_code/styles src/poor_code/ui/styles
```

- [ ] **Step 2: Update imports in `ui/screens/welcome.py`**

The current file imports:
```python
from poor_code.widgets.banner import Banner
from poor_code.widgets.prompt_box import PromptBox
```

Replace with:
```python
from poor_code.ui.widgets.banner import Banner
from poor_code.ui.widgets.prompt_box import PromptBox
```

- [ ] **Step 3: Update `app.py` to use `ui/screens` import and new CSS_PATH**

Current `src/poor_code/app.py`:
```python
from textual.app import App

from poor_code.screens.welcome import WelcomeScreen


class PoorCodeApp(App):
    CSS_PATH = "styles/app.tcss"
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())
```

Replace with:
```python
from textual.app import App

from poor_code.ui.screens.welcome import WelcomeScreen


class PoorCodeApp(App):
    CSS_PATH = "ui/styles/app.tcss"
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())
```

- [ ] **Step 4: Smoke test — import and construct App**

Run: `uv run python -c "from poor_code.app import PoorCodeApp; a = PoorCodeApp(); print(a.css_path)"`
Expected: prints a path ending in `src/poor_code/ui/styles/app.tcss`. No exception.

- [ ] **Step 5: Smoke test — Textual run_test mounts WelcomeScreen**

Run:

```bash
uv run python -c "
import asyncio
from poor_code.app import PoorCodeApp
from poor_code.ui.screens.welcome import WelcomeScreen
async def smoke():
    async with PoorCodeApp().run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        assert isinstance(pilot.app.screen, WelcomeScreen)
        print('OK')
asyncio.run(smoke())
"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/poor_code/
git commit -m "refactor: move screens/widgets/styles under ui/ subpackage"
```

---

## Task 3: `messages.py` — Commands

**Files:**
- Create: `src/poor_code/messages.py`
- Create: `tests/test_messages.py`

- [ ] **Step 1: Write failing test for Command dataclasses**

Create `tests/test_messages.py`:

```python
import dataclasses

import pytest

from poor_code.messages import CancelTurn, Command, RunSlashCommand, SendPrompt


def test_send_prompt_carries_text_and_unique_cmd_id():
    a = SendPrompt(text="hi")
    b = SendPrompt(text="hi")
    assert a.text == "hi"
    assert a.cmd_id != b.cmd_id
    assert isinstance(a.cmd_id, str) and len(a.cmd_id) > 0


def test_run_slash_command_carries_name_and_args_tuple():
    cmd = RunSlashCommand(name="help", args=("--verbose",))
    assert cmd.name == "help"
    assert cmd.args == ("--verbose",)
    assert isinstance(cmd.args, tuple)


def test_cancel_turn_has_only_cmd_id():
    cmd = CancelTurn()
    assert isinstance(cmd.cmd_id, str) and len(cmd.cmd_id) > 0


@pytest.mark.parametrize("cls,kwargs", [
    (SendPrompt, {"text": "x"}),
    (CancelTurn, {}),
    (RunSlashCommand, {"name": "foo"}),
])
def test_commands_are_frozen(cls, kwargs):
    cmd = cls(**kwargs)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cmd.cmd_id = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize("cls,kwargs", [
    (SendPrompt, {"text": "x"}),
    (CancelTurn, {}),
    (RunSlashCommand, {"name": "foo"}),
])
def test_commands_are_subclass_of_command(cls, kwargs):
    assert isinstance(cls(**kwargs), Command)
```

- [ ] **Step 2: Run test, confirm it fails**

Run: `uv run pytest tests/test_messages.py -v`
Expected: ImportError / collection error — `poor_code.messages` does not exist.

- [ ] **Step 3: Implement Command side of `messages.py`**

Create `src/poor_code/messages.py`:

```python
"""Contract between UI and domain.

UI dispatches Commands, domain emits Events. Both are immutable dataclasses.
This module depends only on the standard library and is importable from
anywhere in the package. See docs/superpowers/specs/2026-05-20-ui-app-architecture-design.md.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


def _new_id() -> str:
    return uuid.uuid4().hex


# =========================================================================
# Commands — UI → domain
# =========================================================================


@dataclass(frozen=True)
class Command:
    """Marker base. Concrete commands subclass this."""


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

- [ ] **Step 4: Run test, confirm it passes**

Run: `uv run pytest tests/test_messages.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/messages.py tests/test_messages.py
git commit -m "feat(messages): add Command dataclasses (SendPrompt, CancelTurn, RunSlashCommand)"
```

---

## Task 4: `messages.py` — Events

**Files:**
- Modify: `src/poor_code/messages.py`
- Modify: `tests/test_messages.py`

- [ ] **Step 1: Append failing tests for Event dataclasses**

Append to `tests/test_messages.py`:

```python
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    Event,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnded,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
)


def test_turn_started_correlates_command_and_generates_turn_id():
    ev = TurnStarted(cmd_id="abc")
    other = TurnStarted(cmd_id="abc")
    assert ev.cmd_id == "abc"
    assert ev.turn_id != other.turn_id
    assert isinstance(ev.turn_id, str) and len(ev.turn_id) > 0


def test_assistant_text_delta_is_chunk_not_cumulative():
    # The contract is that .text is the chunk; reducer accumulates.
    ev = AssistantTextDelta(turn_id="t1", text="hello")
    assert ev.text == "hello"


def test_tool_call_started_carries_args_dict():
    ev = ToolCallStarted(turn_id="t1", tool_call_id="c1", tool_name="bash",
                         args={"cmd": "ls"})
    assert ev.args == {"cmd": "ls"}


def test_usage_updated_field_names_match_provider_response_usage_dict():
    # Spec pins: ProviderResponse.usage keys = field names of UsageUpdated.
    # Verified by constructing via **kwargs.
    ev = UsageUpdated(turn_id="t1", input_tokens=10, output_tokens=20, cost_usd=0.001)
    assert ev.input_tokens == 10 and ev.output_tokens == 20 and ev.cost_usd == 0.001


@pytest.mark.parametrize("ev", [
    TurnStarted(cmd_id="c"),
    TurnEnded(turn_id="t"),
    TurnFailed(turn_id="t", error="x"),
    AssistantTextDelta(turn_id="t", text="x"),
    AssistantMessageCompleted(turn_id="t", text="x"),
    ToolCallStarted(turn_id="t", tool_call_id="c", tool_name="n", args={}),
    ToolCallFinished(turn_id="t", tool_call_id="c", result=None),
    ToolCallFailed(turn_id="t", tool_call_id="c", error="x"),
    UsageUpdated(turn_id="t", input_tokens=0, output_tokens=0, cost_usd=0.0),
])
def test_events_are_frozen_and_subclass_event(ev):
    assert isinstance(ev, Event)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.turn_id = "mutated"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_messages.py -v`
Expected: ImportError on the new symbols.

- [ ] **Step 3: Extend `src/poor_code/messages.py` with Events**

Append to `src/poor_code/messages.py`:

```python
# =========================================================================
# Events — domain → UI
# =========================================================================


@dataclass(frozen=True)
class Event:
    """Marker base. Concrete events subclass this."""


# --- Turn lifecycle ---


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


# --- Streaming output ---


@dataclass(frozen=True)
class AssistantTextDelta(Event):
    """One chunk of streaming text. Reducer accumulates per turn."""
    turn_id: str
    text: str


@dataclass(frozen=True)
class AssistantMessageCompleted(Event):
    turn_id: str
    text: str


# --- Tool calls ---


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


# --- Telemetry ---


@dataclass(frozen=True)
class UsageUpdated(Event):
    turn_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `uv run pytest tests/test_messages.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/messages.py tests/test_messages.py
git commit -m "feat(messages): add Event dataclasses (lifecycle, streaming, tool calls, usage)"
```

---

## Task 5: `ui/store.py` — AppState and view dataclasses

**Files:**
- Create: `src/poor_code/ui/store.py`
- Create: `tests/ui/test_store.py`

- [ ] **Step 1: Write failing tests for AppState defaults**

Create `tests/ui/test_store.py`:

```python
import dataclasses

import pytest

from poor_code.ui.store import AppState, ToolCallView, TurnView, UsageState


def test_app_state_defaults():
    s = AppState()
    assert s.turns == ()
    assert s.is_processing is False
    assert s.usage == UsageState()
    assert s.last_error is None
    assert s.cwd == ""


def test_turn_view_defaults():
    t = TurnView(turn_id=None, cmd_id="c1", user_text="hi")
    assert t.turn_id is None
    assert t.assistant_text == ""
    assert t.tool_calls == ()
    assert t.status == "pending"
    assert t.error is None


def test_tool_call_view_required_fields():
    tc = ToolCallView(
        tool_call_id="tc1", tool_name="bash",
        args={"cmd": "ls"}, status="running",
    )
    assert tc.result is None and tc.error is None


def test_view_dataclasses_are_frozen():
    s = AppState()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.is_processing = True  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        UsageState().input_tokens = 5  # type: ignore[misc]
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement view dataclasses in `ui/store.py`**

Create `src/poor_code/ui/store.py`:

```python
"""UI state, UI-internal actions, and the Store/reducer.

The Store holds a single immutable AppState. dispatch(action) runs a pure
reducer; subscribers fire on state change. See spec §3.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal


# =========================================================================
# View state — what the UI renders. All frozen.
# =========================================================================


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
    turn_id: str | None      # None while pending (before TurnStarted arrives)
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

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/ui/store.py tests/ui/test_store.py
git commit -m "feat(store): add AppState + view dataclasses (TurnView, ToolCallView, UsageState)"
```

---

## Task 6: `ui/store.py` — UIAction + reducer no-op skeleton

**Files:**
- Modify: `src/poor_code/ui/store.py`
- Modify: `tests/ui/test_store.py`

- [ ] **Step 1: Add failing test for reducer no-op**

Append to `tests/ui/test_store.py`:

```python
from dataclasses import dataclass

from poor_code.ui.store import Action, AppState, UIAction, reduce


def test_reducer_returns_same_state_for_unknown_action():
    @dataclass(frozen=True)
    class _Unknown(UIAction):
        pass

    s = AppState(cwd="/x")
    out = reduce(s, _Unknown())  # type: ignore[arg-type]
    assert out is s  # identity, not just equality
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/ui/test_store.py::test_reducer_returns_same_state_for_unknown_action -v`
Expected: ImportError on `Action`/`UIAction`/`reduce`.

- [ ] **Step 3: Add UIAction marker + skeleton reducer**

Append to `src/poor_code/ui/store.py`:

```python
from poor_code.messages import Event


# =========================================================================
# UIAction — UI-internal signals. Domain cannot import from this module
# (enforced by lint rule, see spec D8).
# =========================================================================


@dataclass(frozen=True)
class UIAction:
    """Marker base. Concrete UI actions subclass this."""


Action = Event | UIAction


# =========================================================================
# Reducer — pure function. Cases added incrementally in later tasks.
# =========================================================================


def reduce(state: AppState, action: Action) -> AppState:
    match action:
        case _:
            return state
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: 5 passed (4 from Task 5 + new one).

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/ui/store.py tests/ui/test_store.py
git commit -m "feat(store): add UIAction marker base and reducer skeleton"
```

---

## Task 7: Reducer — turn lifecycle cases

**Files:**
- Modify: `src/poor_code/ui/store.py`
- Modify: `tests/ui/test_store.py`

This task adds: `PromptSubmitted` (UIAction), then reducer cases for `PromptSubmitted`, `TurnStarted`, `TurnEnded`, `TurnFailed`.

- [ ] **Step 1: Append failing tests for turn lifecycle**

Append to `tests/ui/test_store.py`:

```python
from poor_code.messages import TurnEnded, TurnFailed, TurnStarted
from poor_code.ui.store import PromptSubmitted


def test_prompt_submitted_appends_pending_turn_and_sets_processing():
    s = AppState()
    s2 = reduce(s, PromptSubmitted(cmd_id="c1", user_text="hi"))
    assert len(s2.turns) == 1
    t = s2.turns[0]
    assert t.cmd_id == "c1" and t.user_text == "hi"
    assert t.turn_id is None and t.status == "pending"
    assert s2.is_processing is True


def test_turn_started_promotes_pending_turn_with_turn_id_and_running_status():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c1", user_text="hi"))
    s = reduce(s, TurnStarted(cmd_id="c1", turn_id="T1"))
    assert s.turns[0].turn_id == "T1"
    assert s.turns[0].status == "running"


def test_turn_started_with_unknown_cmd_id_is_noop():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c1", user_text="hi"))
    out = reduce(s, TurnStarted(cmd_id="UNKNOWN", turn_id="T1"))
    assert out is s


def test_turn_ended_marks_done_and_clears_processing():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c1", user_text="hi"))
    s = reduce(s, TurnStarted(cmd_id="c1", turn_id="T1"))
    s = reduce(s, TurnEnded(turn_id="T1"))
    assert s.turns[0].status == "done"
    assert s.is_processing is False


def test_turn_failed_marks_failed_clears_processing_records_last_error():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c1", user_text="hi"))
    s = reduce(s, TurnStarted(cmd_id="c1", turn_id="T1"))
    s = reduce(s, TurnFailed(turn_id="T1", error="boom"))
    assert s.turns[0].status == "failed"
    assert s.turns[0].error == "boom"
    assert s.last_error == "boom"
    assert s.is_processing is False
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: import error on `PromptSubmitted`, then case failures.

- [ ] **Step 3: Add `PromptSubmitted` UIAction + lifecycle reducer cases + helpers**

Edit `src/poor_code/ui/store.py`. After the `UIAction` declaration (before `Action = ...`), add:

```python
@dataclass(frozen=True)
class PromptSubmitted(UIAction):
    cmd_id: str
    user_text: str
```

Then add helpers and update the reducer. Replace the entire `def reduce(...)` block with:

```python
# --- internal helpers ---


def _update_turn_at(
    turns: tuple[TurnView, ...], index: int, **changes: Any
) -> tuple[TurnView, ...]:
    new = replace(turns[index], **changes)
    return turns[:index] + (new,) + turns[index + 1 :]


def _find_turn_by_cmd(state: AppState, cmd_id: str) -> int | None:
    for i, t in enumerate(state.turns):
        if t.cmd_id == cmd_id:
            return i
    return None


def _find_turn_by_id(state: AppState, turn_id: str) -> int | None:
    for i, t in enumerate(state.turns):
        if t.turn_id == turn_id:
            return i
    return None


# --- reducer ---


def reduce(state: AppState, action: Action) -> AppState:
    match action:
        case PromptSubmitted(cmd_id=cid, user_text=text):
            new_turn = TurnView(
                turn_id=None, cmd_id=cid, user_text=text, status="pending"
            )
            return replace(
                state, turns=state.turns + (new_turn,), is_processing=True
            )

        case TurnStarted(cmd_id=cid, turn_id=tid):
            i = _find_turn_by_cmd(state, cid)
            if i is None:
                return state
            return replace(
                state, turns=_update_turn_at(state.turns, i, turn_id=tid, status="running")
            )

        case TurnEnded(turn_id=tid):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            return replace(
                state,
                turns=_update_turn_at(state.turns, i, status="done"),
                is_processing=False,
            )

        case TurnFailed(turn_id=tid, error=err):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            return replace(
                state,
                turns=_update_turn_at(state.turns, i, status="failed", error=err),
                is_processing=False,
                last_error=err,
            )

        case _:
            return state
```

You also need to import the lifecycle Event types. Update the import near the top of `ui/store.py`:

```python
from poor_code.messages import Event, TurnEnded, TurnFailed, TurnStarted
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/ui/store.py tests/ui/test_store.py
git commit -m "feat(store): handle PromptSubmitted + turn lifecycle events in reducer"
```

---

## Task 8: Reducer — streaming, tool calls, telemetry, cwd

**Files:**
- Modify: `src/poor_code/ui/store.py`
- Modify: `tests/ui/test_store.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/ui/test_store.py`:

```python
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    UsageUpdated,
)
from poor_code.ui.store import CwdChanged


def _running_state(turn_id: str = "T1", cmd_id: str = "c1") -> AppState:
    s = reduce(AppState(), PromptSubmitted(cmd_id=cmd_id, user_text="hi"))
    return reduce(s, TurnStarted(cmd_id=cmd_id, turn_id=turn_id))


def test_assistant_text_delta_accumulates():
    s = _running_state()
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="hel"))
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="lo"))
    assert s.turns[0].assistant_text == "hello"


def test_assistant_message_completed_replaces_assistant_text():
    s = _running_state()
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="partial"))
    s = reduce(s, AssistantMessageCompleted(turn_id="T1", text="final answer"))
    assert s.turns[0].assistant_text == "final answer"


def test_tool_call_started_appends_running_tool_call():
    s = _running_state()
    s = reduce(s, ToolCallStarted(
        turn_id="T1", tool_call_id="tc1", tool_name="bash", args={"cmd": "ls"}
    ))
    tc = s.turns[0].tool_calls[0]
    assert tc.tool_call_id == "tc1" and tc.tool_name == "bash"
    assert tc.args == {"cmd": "ls"} and tc.status == "running"


def test_tool_call_finished_updates_status_and_result():
    s = _running_state()
    s = reduce(s, ToolCallStarted(
        turn_id="T1", tool_call_id="tc1", tool_name="bash", args={}
    ))
    s = reduce(s, ToolCallFinished(turn_id="T1", tool_call_id="tc1", result="ok"))
    tc = s.turns[0].tool_calls[0]
    assert tc.status == "done" and tc.result == "ok"


def test_tool_call_failed_updates_status_and_error():
    s = _running_state()
    s = reduce(s, ToolCallStarted(
        turn_id="T1", tool_call_id="tc1", tool_name="bash", args={}
    ))
    s = reduce(s, ToolCallFailed(turn_id="T1", tool_call_id="tc1", error="bad"))
    tc = s.turns[0].tool_calls[0]
    assert tc.status == "failed" and tc.error == "bad"


def test_usage_updated_accumulates():
    s = _running_state()
    s = reduce(s, UsageUpdated(turn_id="T1",
                               input_tokens=10, output_tokens=20, cost_usd=0.5))
    s = reduce(s, UsageUpdated(turn_id="T1",
                               input_tokens=5, output_tokens=5, cost_usd=0.25))
    assert s.usage.input_tokens == 15
    assert s.usage.output_tokens == 25
    assert s.usage.cost_usd == 0.75


def test_cwd_changed_updates_cwd_only():
    s = AppState(cwd="/old")
    s2 = reduce(s, CwdChanged(cwd="/new"))
    assert s2.cwd == "/new"
    assert s2.turns == s.turns  # untouched
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: failures / import errors on the new cases.

- [ ] **Step 3: Add `CwdChanged`, helpers, and new reducer cases**

Edit `src/poor_code/ui/store.py`.

First, update imports at the top to include all message types used:

```python
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    Event,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnded,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
)
```

Add the new UIAction next to `PromptSubmitted`:

```python
@dataclass(frozen=True)
class CwdChanged(UIAction):
    cwd: str
```

Add the tool-call helper near the other helpers:

```python
def _update_tool_call(
    state: AppState, turn_id: str, tool_call_id: str, **changes: Any
) -> AppState:
    i = _find_turn_by_id(state, turn_id)
    if i is None:
        return state
    turn = state.turns[i]
    for j, tc in enumerate(turn.tool_calls):
        if tc.tool_call_id == tool_call_id:
            new_tc = replace(tc, **changes)
            new_tcs = turn.tool_calls[:j] + (new_tc,) + turn.tool_calls[j + 1 :]
            return replace(
                state, turns=_update_turn_at(state.turns, i, tool_calls=new_tcs)
            )
    return state


def _append_tool_call(
    state: AppState, turn_id: str, tc: ToolCallView
) -> AppState:
    i = _find_turn_by_id(state, turn_id)
    if i is None:
        return state
    turn = state.turns[i]
    return replace(
        state,
        turns=_update_turn_at(state.turns, i, tool_calls=turn.tool_calls + (tc,)),
    )
```

Then extend the `reduce()` match block. Insert new cases *before* the final `case _:`:

```python
        case AssistantTextDelta(turn_id=tid, text=chunk):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            new_text = state.turns[i].assistant_text + chunk
            return replace(
                state, turns=_update_turn_at(state.turns, i, assistant_text=new_text)
            )

        case AssistantMessageCompleted(turn_id=tid, text=text):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            return replace(
                state, turns=_update_turn_at(state.turns, i, assistant_text=text)
            )

        case ToolCallStarted(turn_id=tid, tool_call_id=tcid, tool_name=name, args=args):
            return _append_tool_call(
                state, tid,
                ToolCallView(tool_call_id=tcid, tool_name=name, args=args, status="running"),
            )

        case ToolCallFinished(turn_id=tid, tool_call_id=tcid, result=r):
            return _update_tool_call(state, tid, tcid, status="done", result=r)

        case ToolCallFailed(turn_id=tid, tool_call_id=tcid, error=err):
            return _update_tool_call(state, tid, tcid, status="failed", error=err)

        case UsageUpdated(input_tokens=i_in, output_tokens=i_out, cost_usd=c):
            return replace(state, usage=UsageState(
                input_tokens=state.usage.input_tokens + i_in,
                output_tokens=state.usage.output_tokens + i_out,
                cost_usd=state.usage.cost_usd + c,
            ))

        case CwdChanged(cwd=cwd):
            return replace(state, cwd=cwd)
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/ui/store.py tests/ui/test_store.py
git commit -m "feat(store): handle streaming + tool calls + usage + cwd in reducer"
```

---

## Task 9: `ui/store.py` — Store class (dispatch + subscribe)

**Files:**
- Modify: `src/poor_code/ui/store.py`
- Modify: `tests/ui/test_store.py`

- [ ] **Step 1: Append failing tests for Store**

Append to `tests/ui/test_store.py`:

```python
from poor_code.ui.store import Store


def test_store_starts_with_initial_state():
    init = AppState(cwd="/x")
    assert Store(init).state is init


def test_store_dispatch_runs_reducer_and_updates_state():
    s = Store(AppState())
    s.dispatch(PromptSubmitted(cmd_id="c1", user_text="hi"))
    assert s.state.is_processing is True
    assert len(s.state.turns) == 1


def test_store_subscribe_fires_on_state_change():
    s = Store(AppState())
    seen: list[AppState] = []
    s.subscribe(seen.append)
    s.dispatch(PromptSubmitted(cmd_id="c1", user_text="hi"))
    assert len(seen) == 1
    assert seen[0] is s.state


def test_store_subscribe_does_not_fire_when_state_unchanged():
    @dataclass(frozen=True)
    class _NoOp(UIAction):
        pass

    s = Store(AppState())
    seen: list[AppState] = []
    s.subscribe(seen.append)
    s.dispatch(_NoOp())  # type: ignore[arg-type]
    assert seen == []


def test_store_unsubscribe_stops_callbacks():
    s = Store(AppState())
    seen: list[AppState] = []
    unsub = s.subscribe(seen.append)
    unsub()
    s.dispatch(PromptSubmitted(cmd_id="c1", user_text="hi"))
    assert seen == []
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: ImportError on `Store`.

- [ ] **Step 3: Implement Store class**

Append to `src/poor_code/ui/store.py`:

```python
# =========================================================================
# Store — single source of truth for UI state. Single asyncio loop.
# =========================================================================


class Store:
    """Holds current AppState; dispatch(action) → reducer → notify listeners."""

    def __init__(self, initial: AppState) -> None:
        self._state = initial
        self._listeners: list[Callable[[AppState], None]] = []

    @property
    def state(self) -> AppState:
        return self._state

    def dispatch(self, action: Action) -> None:
        new = reduce(self._state, action)
        if new is self._state:
            return
        self._state = new
        for listener in list(self._listeners):
            listener(new)

    def subscribe(
        self, listener: Callable[[AppState], None]
    ) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsub() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsub
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/ui/test_store.py -v`
Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/ui/store.py tests/ui/test_store.py
git commit -m "feat(store): add Store class with dispatch + subscribe"
```

---

## Task 10: `domain/` skeleton — Agent Protocol only

**Files:**
- Create: `src/poor_code/domain/__init__.py`
- Create: `src/poor_code/domain/agent.py`
- Create: `src/poor_code/infra/__init__.py`

- [ ] **Step 1: Create empty `domain/__init__.py` and `infra/__init__.py`**

```bash
mkdir -p src/poor_code/domain src/poor_code/infra
touch src/poor_code/domain/__init__.py
touch src/poor_code/infra/__init__.py
```

- [ ] **Step 2: Write the Agent Protocol**

Create `src/poor_code/domain/agent.py`:

```python
"""Agent Protocol.

The body of this module — real Agent class, inner loop, hooks wiring — is
deferred per spec until the first real Provider lands. Here we define ONLY
the Protocol that the UI side depends on, so PoorCodeApp can be typed and
test doubles (EchoAgent, FakeAgent) can be substituted freely.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Protocol, runtime_checkable

from poor_code.messages import Command, Event


@runtime_checkable
class Agent(Protocol):
    async def run(
        self, cmd: Command, cancel: asyncio.Event
    ) -> AsyncIterator[Event]:
        """Process a Command, yield Events until the turn ends or is cancelled.

        Implementations MUST be cooperative w.r.t. `cancel.is_set()` and yield
        a terminal Event (TurnEnded or TurnFailed) before returning.
        """
        ...
```

- [ ] **Step 3: Smoke test — import works**

Run: `uv run python -c "from poor_code.domain.agent import Agent; print(Agent)"`
Expected: `<class 'poor_code.domain.agent.Agent'>` (or `typing.Protocol[Agent]`-style print)

- [ ] **Step 4: Commit**

```bash
git add src/poor_code/domain/ src/poor_code/infra/
git commit -m "feat(domain): add Agent Protocol; create empty domain/ and infra/ packages"
```

---

## Task 11: `EchoAgent` — minimal demo Agent

**Files:**
- Create: `src/poor_code/domain/echo_agent.py`
- Create: `tests/domain/__init__.py`
- Create: `tests/domain/test_echo_agent.py`

- [ ] **Step 1: Create tests/domain dir and write failing test**

```bash
mkdir -p tests/domain
touch tests/domain/__init__.py
```

Create `tests/domain/test_echo_agent.py`:

```python
import asyncio

from poor_code.domain.echo_agent import EchoAgent
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    SendPrompt,
    TurnEnded,
    TurnStarted,
)


async def _drain(agent, cmd, cancel):
    return [ev async for ev in agent.run(cmd, cancel)]


async def test_echo_agent_yields_expected_event_sequence():
    agent = EchoAgent()
    cmd = SendPrompt(text="hello")
    cancel = asyncio.Event()
    events = await _drain(agent, cmd, cancel)

    types = [type(e).__name__ for e in events]
    assert types[0] == "TurnStarted"
    assert types[-1] == "TurnEnded"
    # At least one delta and one completed in between
    assert any(isinstance(e, AssistantTextDelta) for e in events)
    assert any(isinstance(e, AssistantMessageCompleted) for e in events)


async def test_echo_agent_uses_same_turn_id_across_events():
    agent = EchoAgent()
    cmd = SendPrompt(text="hi")
    events = [ev async for ev in agent.run(cmd, asyncio.Event())]
    turn_started = next(e for e in events if isinstance(e, TurnStarted))
    assert turn_started.cmd_id == cmd.cmd_id
    for e in events[1:]:
        assert getattr(e, "turn_id") == turn_started.turn_id


async def test_echo_agent_completed_text_contains_input():
    agent = EchoAgent()
    events = [ev async for ev in agent.run(SendPrompt(text="ping"), asyncio.Event())]
    final = next(e for e in events if isinstance(e, AssistantMessageCompleted))
    assert "ping" in final.text


async def test_echo_agent_respects_cancel_between_yields():
    agent = EchoAgent()
    cancel = asyncio.Event()
    cancel.set()  # cancel before we even start
    events = [ev async for ev in agent.run(SendPrompt(text="x"), cancel)]
    assert events[-1].__class__.__name__ == "TurnFailed"
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/domain/test_echo_agent.py -v`
Expected: ImportError on `EchoAgent`.

- [ ] **Step 3: Implement `EchoAgent`**

Create `src/poor_code/domain/echo_agent.py`:

```python
"""EchoAgent — minimal demo Agent for v0 wiring and tests.

Yields a deterministic Event sequence that echoes the user's input. Has no
LLM dependency. Used by `cli.py` as the default Agent for `uv run poor-code`
and by integration tests to drive the UI flow.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    Command,
    Event,
    RunSlashCommand,
    SendPrompt,
    TurnEnded,
    TurnFailed,
    TurnStarted,
)


class EchoAgent:
    """Implements the Agent Protocol. No state retained between turns."""

    async def run(
        self, cmd: Command, cancel: asyncio.Event
    ) -> AsyncIterator[Event]:
        turn_id = uuid.uuid4().hex

        # Always emit TurnStarted first (gives UI a turn_id to bind to).
        if isinstance(cmd, SendPrompt):
            user_text = cmd.text
            cmd_id = cmd.cmd_id
        elif isinstance(cmd, RunSlashCommand):
            user_text = f"/{cmd.name} {' '.join(cmd.args)}".strip()
            cmd_id = cmd.cmd_id
        else:
            yield TurnFailed(turn_id=turn_id, error=f"unsupported command: {type(cmd).__name__}")
            return

        yield TurnStarted(cmd_id=cmd_id, turn_id=turn_id)

        if cancel.is_set():
            yield TurnFailed(turn_id=turn_id, error="cancelled")
            return

        reply = f"echo: {user_text}"
        # Stream the reply word-by-word so the UI shows incremental updates.
        words = reply.split(" ")
        emitted = ""
        for i, word in enumerate(words):
            if cancel.is_set():
                yield TurnFailed(turn_id=turn_id, error="cancelled")
                return
            chunk = (" " if i > 0 else "") + word
            emitted += chunk
            yield AssistantTextDelta(turn_id=turn_id, text=chunk)
            await asyncio.sleep(0.01)  # cooperative yield + tiny visual stagger

        yield AssistantMessageCompleted(turn_id=turn_id, text=emitted)
        yield TurnEnded(turn_id=turn_id)
```

Note: `_new_id` is imported from `messages.py` where it was defined as a module-level helper.

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/domain/test_echo_agent.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/domain/echo_agent.py tests/domain/
git commit -m "feat(domain): add EchoAgent demo for v0 wiring + tests"
```

---

## Task 12: Wire `PoorCodeApp` — Store, reactive bridge, submit(), worker, cancel

**Files:**
- Modify: `src/poor_code/app.py`
- Modify: `src/poor_code/cli.py`

- [ ] **Step 1: Rewrite `src/poor_code/app.py` with full wiring**

Replace the entire contents of `src/poor_code/app.py` with:

```python
from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App
from textual.reactive import reactive

from poor_code.domain.agent import Agent
from poor_code.messages import Command, RunSlashCommand, SendPrompt
from poor_code.ui.screens.welcome import WelcomeScreen
from poor_code.ui.store import AppState, PromptSubmitted, Store


class PoorCodeApp(App):
    CSS_PATH = "ui/styles/app.tcss"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "cancel_or_quit", "Cancel/Quit"),
    ]

    # Bridge from Store → Textual watcher system. Widgets observe this.
    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self.store = Store(AppState(cwd=str(Path.cwd())))
        self.agent = agent
        self._cancel = asyncio.Event()

    def on_mount(self) -> None:
        self.store.subscribe(lambda s: setattr(self, "app_state", s))
        self.app_state = self.store.state
        self.push_screen(WelcomeScreen())

    # --- public single entry point for widgets ---

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

- [ ] **Step 2: Update `cli.py` to inject `EchoAgent`**

Replace the contents of `src/poor_code/cli.py`:

```python
from poor_code.app import PoorCodeApp
from poor_code.domain.echo_agent import EchoAgent


def main() -> None:
    PoorCodeApp(agent=EchoAgent()).run()
```

- [ ] **Step 3: Smoke test — App constructs with an Agent**

Run:

```bash
uv run python -c "
from poor_code.app import PoorCodeApp
from poor_code.domain.echo_agent import EchoAgent
a = PoorCodeApp(agent=EchoAgent())
print('store:', type(a.store).__name__, 'agent:', type(a.agent).__name__)
print('css:', a.css_path)
"
```
Expected:
```
store: Store agent: EchoAgent
css: [PosixPath('.../src/poor_code/ui/styles/app.tcss')]
```

- [ ] **Step 4: Smoke test — run_test still mounts the welcome screen**

Run:

```bash
uv run python -c "
import asyncio
from poor_code.app import PoorCodeApp
from poor_code.domain.echo_agent import EchoAgent
from poor_code.ui.screens.welcome import WelcomeScreen
async def smoke():
    async with PoorCodeApp(agent=EchoAgent()).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        assert isinstance(pilot.app.screen, WelcomeScreen)
        print('OK')
asyncio.run(smoke())
"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/app.py src/poor_code/cli.py
git commit -m "feat(app): wire Store + reactive bridge + submit() + cancel; inject EchoAgent in cli"
```

---

## Task 13: PromptBox calls `app.submit()`

**Files:**
- Modify: `src/poor_code/ui/widgets/prompt_box.py`

- [ ] **Step 1: Update PromptBox to forward input to `app.submit`**

Replace `src/poor_code/ui/widgets/prompt_box.py` with:

```python
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Input


class PromptBox(Container):
    def compose(self) -> ComposeResult:
        yield Input(
            placeholder='Try "explain the philosophy in docs/"',
            id="prompt-input",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value
        self.query_one(Input).value = ""
        self.app.submit(text)
```

- [ ] **Step 2: Smoke test — Pilot types into the Input and submit fires**

Run:

```bash
uv run python -c "
import asyncio
from poor_code.app import PoorCodeApp
from poor_code.domain.echo_agent import EchoAgent
from textual.widgets import Input

async def smoke():
    async with PoorCodeApp(agent=EchoAgent()).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        inp = pilot.app.query_one(Input)
        inp.focus()
        await pilot.press('h', 'i')
        await pilot.press('enter')
        await pilot.pause()
        # The optimistic PromptSubmitted should have created one turn
        assert len(pilot.app.store.state.turns) == 1
        assert pilot.app.store.state.turns[0].user_text == 'hi'
        print('OK')

asyncio.run(smoke())
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/poor_code/ui/widgets/prompt_box.py
git commit -m "feat(prompt-box): forward Input.Submitted to app.submit()"
```

---

## Task 14: `ChatLog` widget — render `state.turns`

**Files:**
- Create: `src/poor_code/ui/widgets/chat_log.py`
- Modify: `src/poor_code/ui/screens/welcome.py`
- Modify: `src/poor_code/ui/styles/app.tcss`

- [ ] **Step 1: Implement `ChatLog`**

Create `src/poor_code/ui/widgets/chat_log.py`:

```python
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from poor_code.ui.store import AppState


class ChatLog(Widget):
    """Renders state.turns. Naive remount on each state change.

    Diff-aware updates are deferred; performance is fine for hundreds of turns.
    """

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat-scroll")

    def on_mount(self) -> None:
        self.watch(self.app, "app_state", self._render)

    def _render(self, state: AppState) -> None:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.remove_children()
        for turn in state.turns:
            scroll.mount(Static(f"> {turn.user_text}", classes="user-msg"))
            if turn.assistant_text:
                scroll.mount(Static(turn.assistant_text, classes="assistant-msg"))
            for tc in turn.tool_calls:
                marker = {"running": "…", "done": "✓", "failed": "✗"}[tc.status]
                scroll.mount(Static(
                    f"  {marker} {tc.tool_name}", classes=f"tool-{tc.status}"
                ))
            if turn.status == "failed" and turn.error:
                scroll.mount(Static(f"  error: {turn.error}", classes="turn-error"))
```

- [ ] **Step 2: Add `ChatLog` to `WelcomeScreen`**

Replace `src/poor_code/ui/screens/welcome.py` with:

```python
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static

from poor_code.ui.widgets.banner import Banner
from poor_code.ui.widgets.chat_log import ChatLog
from poor_code.ui.widgets.prompt_box import PromptBox

_TAGLINE = "small models, strong scaffolding."

_TIPS = (
    "Tips for getting started:\n"
    "  1. Ask a question, edit files, or run commands.\n"
    "  2. Be specific for the best results.\n"
    "  3. /help for more, ctrl+q to exit."
)


class WelcomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Banner()
        yield Static(_TAGLINE, classes="tagline")
        yield Static(_TIPS, classes="tips")
        yield Static(f"cwd: {Path.cwd()}", classes="cwd")
        yield ChatLog(id="chat-log")
        yield PromptBox()
```

- [ ] **Step 3: Add CSS for ChatLog rows**

Append to `src/poor_code/ui/styles/app.tcss`:

```css
#chat-log {
    height: 1fr;
    margin-top: 1;
}

#chat-scroll {
    height: 100%;
}

.user-msg {
    color: $accent;
    margin-bottom: 1;
}

.assistant-msg {
    color: $text;
    margin-bottom: 1;
}

.tool-running { color: $warning; }
.tool-done    { color: $success; }
.tool-failed  { color: $error; }

.turn-error {
    color: $error;
}
```

- [ ] **Step 4: Smoke test — ChatLog renders a turn after submit**

Run:

```bash
uv run python -c "
import asyncio
from poor_code.app import PoorCodeApp
from poor_code.domain.echo_agent import EchoAgent
from poor_code.ui.widgets.chat_log import ChatLog
from textual.widgets import Input, Static

async def smoke():
    async with PoorCodeApp(agent=EchoAgent()).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.query_one(Input).focus()
        await pilot.press('h', 'i')
        await pilot.press('enter')
        # Give EchoAgent time to stream + emit TurnEnded (~30ms total)
        for _ in range(20):
            await pilot.pause()
        log = pilot.app.query_one(ChatLog)
        statics = list(log.query(Static))
        texts = [s.renderable for s in statics]
        assert any('> hi' in str(t) for t in texts), texts
        assert any('echo: hi' in str(t) for t in texts), texts
        print('OK')

asyncio.run(smoke())
"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/ui/widgets/chat_log.py src/poor_code/ui/screens/welcome.py src/poor_code/ui/styles/app.tcss
git commit -m "feat(ui): add ChatLog widget; embed in WelcomeScreen; add row styles"
```

---

## Task 15: End-to-end test — submit() → Agent → state assertions

**Files:**
- Create: `tests/ui/test_app_flow.py`

- [ ] **Step 1: Write end-to-end test with inline scripted Agents**

Create `tests/ui/test_app_flow.py`:

```python
from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    TurnEnded,
    TurnStarted,
    UsageUpdated,
)


async def test_submit_routes_through_agent_and_updates_store():
    # ScriptedAgent reads the incoming cmd to set correlation IDs correctly.
    class ScriptedAgent:
        async def run(self, cmd, cancel):
            yield TurnStarted(cmd_id=cmd.cmd_id, turn_id="T1")
            yield AssistantTextDelta(turn_id="T1", text="hi ")
            yield AssistantTextDelta(turn_id="T1", text="there")
            yield AssistantMessageCompleted(turn_id="T1", text="hi there")
            yield UsageUpdated(turn_id="T1", input_tokens=2, output_tokens=2, cost_usd=0.0)
            yield TurnEnded(turn_id="T1")

    async with PoorCodeApp(agent=ScriptedAgent()).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.query_one(Input).focus()
        await pilot.press("p", "i", "n", "g")
        await pilot.press("enter")
        # Drain worker; ScriptedAgent has no sleeps but await sleep(0) yields
        for _ in range(20):
            await pilot.pause()

        state = pilot.app.store.state
        assert len(state.turns) == 1
        turn = state.turns[0]
        assert turn.user_text == "ping"
        assert turn.turn_id == "T1"
        assert turn.status == "done"
        assert turn.assistant_text == "hi there"
        assert state.is_processing is False
        assert state.usage.input_tokens == 2
        assert state.usage.output_tokens == 2


async def test_cancel_during_turn_marks_failed():
    """Ctrl+C while processing sets _cancel; ScriptedAgent observes and stops."""

    class SlowAgent:
        async def run(self, cmd, cancel):
            import asyncio as _asyncio
            yield TurnStarted(cmd_id=cmd.cmd_id, turn_id="T1")
            for _ in range(100):
                if cancel.is_set():
                    from poor_code.messages import TurnFailed
                    yield TurnFailed(turn_id="T1", error="cancelled")
                    return
                yield AssistantTextDelta(turn_id="T1", text=".")
                await _asyncio.sleep(0.01)

    async with PoorCodeApp(agent=SlowAgent()).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.query_one(Input).focus()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause()
        # Confirm we are processing
        assert pilot.app.store.state.is_processing is True
        # Trigger cancel
        pilot.app.action_cancel_or_quit()
        for _ in range(20):
            await pilot.pause()
        state = pilot.app.store.state
        assert state.is_processing is False
        assert state.turns[0].status == "failed"
        assert state.last_error == "cancelled"
```

- [ ] **Step 2: Run, confirm pass**

Run: `uv run pytest tests/ui/test_app_flow.py -v`
Expected: 2 passed.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (sum of Tasks 3, 4, 5–9, 11, 15).

- [ ] **Step 4: Commit**

```bash
git add tests/ui/test_app_flow.py
git commit -m "test: end-to-end App.submit → Agent → Store integration"
```

---

## Task 16: Manual verification — `uv run poor-code` shows working echo loop

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `uv run poor-code`

- [ ] **Step 2: Verify welcome shows**

You should see the ASCII banner, tagline, tips, cwd, and an input box at the bottom.

- [ ] **Step 3: Type a prompt and submit**

Type `hello world` and press Enter.

Expected: the chat log area shows `> hello world` and then `echo: hello world` appears (streaming word by word). Input box clears.

- [ ] **Step 4: Submit a second prompt**

Type `ping` and press Enter.

Expected: prior turn remains. New turn appended below: `> ping` then `echo: ping`.

- [ ] **Step 5: Submit a slash command**

Type `/help` and press Enter.

Expected: EchoAgent treats it as a string and shows `> /help` then `echo: /help` (no special handling — SlashCommand routing is wired but EchoAgent intentionally treats it as a string echo).

- [ ] **Step 6: Quit**

Press Ctrl+Q.

Expected: app exits cleanly.

- [ ] **Step 7: Document manual-test result**

This is a manual verification step. The next session should not commit any artifact from this task — the deliverable is "the app runs interactively and shows turns rendering correctly."

If anything in Steps 2–6 looks wrong, file a follow-up task (do not silently fix). Most likely causes if something is off:
- Layout: `app.tcss` heights/margins. Adjust in a follow-up.
- Streaming feels too fast/slow: tweak `asyncio.sleep(0.01)` in `EchoAgent.run`.
- Chat log doesn't update: confirm `ChatLog.on_mount` ran `self.watch(self.app, "app_state", ...)`.

---

## Definition of Done

After all tasks:

1. `uv run pytest -v` — all tests pass.
2. `uv run poor-code` — interactive loop works end-to-end (echo behavior).
3. Folder structure matches spec §1: `messages.py` at root; `ui/{store,screens,widgets,styles}`; `domain/{agent,echo_agent}`; `infra/__init__.py`.
4. No direct domain↔ui imports (verifiable by grep: `git grep "from poor_code.ui" src/poor_code/domain/` and `git grep "import textual" src/poor_code/domain/` both empty).
5. AppState is immutable; reducer is pure; Store has dispatch + subscribe.
6. PoorCodeApp.submit() is the single UI→domain entry; PromptBox calls it.
7. EchoAgent + FakeAgent demonstrate the Agent Protocol can be swapped freely.

## Deferred to future plans (per spec)

- Real `Provider` (Anthropic / Ollama) implementations in `infra/`.
- Real `Tool` implementations (read, edit, bash) in `domain/tool.py` + `domain/tools/`.
- `Hook`, `HookBus`, `Profile`, `SlashCommandRegistry` concrete implementations.
- `pre_sample` hook for conversation pruning (addresses memory-growth concern raised in spec §5).
- import-linter config to mechanically enforce import boundaries.
- Diff-aware ChatLog rendering (current impl re-mounts all children on each state change).
- MCP integration.
