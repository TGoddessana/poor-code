# Slash Autocomplete + Command Metadata — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a declarative argument-shape model to `SlashCommand` and a `/`-triggered autocomplete popup in the chat UI, with a `SlashDispatcher` that keeps `App.submit` focused on dispatch + turn lifecycle.

**Architecture:** Three small units. (1) `slash/base.py` defines `Arg`/`ArgKind`/`ParsedArgs`/`SlashCommand` protocol + `usage_hint()`. (2) `slash/parser.py` parses raw text → `(name, ParsedArgs)` with `UnknownCommand`/`MissingArg` exceptions. (3) `slash/dispatcher.py` owns the parse→execute→notify pipeline. UI side: `PromptBox` mounts an `OptionList` above the `Input`, filters commands as the user types, intercepts ↑↓/Tab/Enter/Esc when the popup is open.

**Tech Stack:** Python 3.14, Textual 8.2.7, pytest 8.3 (asyncio auto).

**Spec:** `docs/superpowers/specs/2026-05-24-slash-autocomplete-design.md`

**Test command:** `uv run pytest <path>` (asyncio_mode=auto — no decorator needed).

---

## Task 1: Command metadata + usage_hint

**Files:**
- Modify: `src/poor_code/slash/base.py` (full rewrite)
- Test: `tests/slash/test_base.py` (new)

- [ ] **Step 1: Write failing tests for `Arg`, `ParsedArgs`, `usage_hint`**

Create `tests/slash/test_base.py`:

```python
from dataclasses import FrozenInstanceError

import pytest

from poor_code.slash.base import Arg, ArgKind, ParsedArgs, usage_hint


def test_arg_is_frozen():
    a = Arg(name="name", kind=ArgKind.TOKEN)
    with pytest.raises(FrozenInstanceError):
        a.name = "other"  # type: ignore[misc]


def test_arg_default_not_optional():
    assert Arg(name="x", kind=ArgKind.TOKEN).optional is False


def test_parsed_args_holds_values_and_raw():
    p = ParsedArgs(values={"name": "foo"}, raw="foo bar")
    assert p.values == {"name": "foo"}
    assert p.raw == "foo bar"


class _FakeCmd:
    name = "skill"
    description = "Run a skill"
    args = (Arg("name", ArgKind.TOKEN), Arg("prompt", ArgKind.REST, optional=True))
    def execute(self, ctx, parsed): pass


class _NoArgCmd:
    name = "login"
    description = "Sign in"
    args: tuple = ()
    def execute(self, ctx, parsed): pass


def test_usage_hint_no_args():
    assert usage_hint(_NoArgCmd()) == "/login"


def test_usage_hint_required_and_optional():
    assert usage_hint(_FakeCmd()) == "/skill <name> [prompt]"
```

- [ ] **Step 2: Run tests, expect ImportError / failures**

Run: `uv run pytest tests/slash/test_base.py -v`
Expected: collection error (`ArgKind`, `usage_hint` not importable from `poor_code.slash.base`).

- [ ] **Step 3: Rewrite `src/poor_code/slash/base.py`**

```python
"""SlashCommand — client-side commands that bypass the LLM.

A SlashCommand owns a verb (`/login`, `/help`, …) and declares its argument
shape so the parser can split tokens vs preserve raw natural-language text,
and so the autocomplete UI can render a usage hint.

SlashContext is the narrow surface the app exposes to commands so commands
don't need to import the full App class.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable


class ArgKind(Enum):
    TOKEN = "token"   # one whitespace-delimited token
    REST = "rest"     # entire remainder of line, raw (for natural language)


@dataclass(frozen=True)
class Arg:
    name: str
    kind: ArgKind
    optional: bool = False


@dataclass(frozen=True)
class ParsedArgs:
    values: dict[str, str]
    raw: str


@runtime_checkable
class SlashContext(Protocol):
    def push_screen(
        self, screen: Any, callback: Callable[[Any], None] | None = None
    ) -> Any: ...
    def notify(self, message: str, *, severity: str = "information") -> None: ...
    def set_llm(self, llm: Any) -> None: ...


@runtime_checkable
class SlashCommand(Protocol):
    name: str
    description: str
    args: tuple[Arg, ...]

    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None: ...


def usage_hint(cmd: SlashCommand) -> str:
    parts = [f"/{cmd.name}"]
    for a in cmd.args:
        parts.append(f"[{a.name}]" if a.optional else f"<{a.name}>")
    return " ".join(parts)
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `uv run pytest tests/slash/test_base.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/slash/base.py tests/slash/test_base.py
git commit -m "feat(slash): declarative arg model + usage_hint"
```

---

## Task 2: Parser

**Files:**
- Create: `src/poor_code/slash/parser.py`
- Test: `tests/slash/test_parser.py` (new)

- [ ] **Step 1: Write failing tests covering all parse cases**

Create `tests/slash/test_parser.py`:

```python
from dataclasses import dataclass

import pytest

from poor_code.slash.base import Arg, ArgKind, ParsedArgs
from poor_code.slash.parser import MissingArg, UnknownCommand, parse
from poor_code.slash.registry import SlashRegistry


@dataclass
class _Cmd:
    name: str
    description: str = "fake"
    args: tuple = ()
    def execute(self, ctx, parsed): pass


def _registry(*cmds) -> SlashRegistry:
    return SlashRegistry(list(cmds))


def test_parse_no_args():
    r = _registry(_Cmd(name="login"))
    name, parsed = parse("/login", r)
    assert name == "login"
    assert parsed.values == {}
    assert parsed.raw == ""


def test_parse_no_args_with_trailing_garbage_is_dropped():
    r = _registry(_Cmd(name="login"))
    name, parsed = parse("/login foo bar", r)
    assert parsed.values == {}
    assert parsed.raw == "foo bar"


def test_parse_single_token():
    r = _registry(_Cmd(name="model", args=(Arg("name", ArgKind.TOKEN),)))
    _, parsed = parse("/model gpt-4", r)
    assert parsed.values == {"name": "gpt-4"}


def test_parse_token_then_rest():
    r = _registry(_Cmd(name="skill", args=(
        Arg("name", ArgKind.TOKEN),
        Arg("prompt", ArgKind.REST),
    )))
    _, parsed = parse("/skill foo do the thing now", r)
    assert parsed.values == {"name": "foo", "prompt": "do the thing now"}
    assert parsed.raw == "foo do the thing now"


def test_parse_rest_only():
    r = _registry(_Cmd(name="explain", args=(Arg("prompt", ArgKind.REST),)))
    _, parsed = parse("/explain how does X work", r)
    assert parsed.values == {"prompt": "how does X work"}


def test_parse_optional_rest_missing_yields_empty():
    r = _registry(_Cmd(name="skill", args=(
        Arg("name", ArgKind.TOKEN),
        Arg("prompt", ArgKind.REST, optional=True),
    )))
    _, parsed = parse("/skill foo", r)
    assert parsed.values == {"name": "foo", "prompt": ""}


def test_parse_missing_required_token_raises():
    cmd = _Cmd(name="model", args=(Arg("name", ArgKind.TOKEN),))
    r = _registry(cmd)
    with pytest.raises(MissingArg) as ei:
        parse("/model", r)
    assert ei.value.arg.name == "name"
    assert ei.value.cmd is cmd


def test_parse_unknown_command_raises():
    with pytest.raises(UnknownCommand) as ei:
        parse("/nope", _registry(_Cmd(name="login")))
    assert ei.value.name == "nope"


def test_parse_collapses_extra_whitespace_between_tokens():
    r = _registry(_Cmd(name="model", args=(Arg("name", ArgKind.TOKEN),)))
    _, parsed = parse("/model    gpt-4", r)
    assert parsed.values == {"name": "gpt-4"}
```

- [ ] **Step 2: Run tests, expect failures**

Run: `uv run pytest tests/slash/test_parser.py -v`
Expected: ImportError on `poor_code.slash.parser`.

- [ ] **Step 3: Implement `src/poor_code/slash/parser.py`**

```python
"""Parse `/name args…` text into (name, ParsedArgs) using a command's arg schema.

REST args grab the entire remainder of the line raw; TOKEN args take one
whitespace-delimited token. Whitespace between tokens is collapsed.
"""
from __future__ import annotations

from poor_code.slash.base import Arg, ArgKind, ParsedArgs, SlashCommand
from poor_code.slash.registry import SlashRegistry


class UnknownCommand(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class MissingArg(Exception):
    def __init__(self, cmd: SlashCommand, arg: Arg) -> None:
        super().__init__(arg.name)
        self.cmd = cmd
        self.arg = arg


def parse(text: str, registry: SlashRegistry) -> tuple[str, ParsedArgs]:
    assert text.startswith("/")
    head, _, rest = text[1:].partition(" ")
    name = head
    cmd = registry.get(name)
    if cmd is None:
        raise UnknownCommand(name)
    rest = rest.strip()
    raw = rest
    values: dict[str, str] = {}
    for arg in cmd.args:
        if arg.kind is ArgKind.REST:
            values[arg.name] = rest
            rest = ""
            break  # REST is validated last by SlashRegistry
        # TOKEN
        token, _, rest = rest.partition(" ")
        rest = rest.lstrip()
        if not token:
            if arg.optional:
                values[arg.name] = ""
                continue
            raise MissingArg(cmd, arg)
        values[arg.name] = token
    return name, ParsedArgs(values=values, raw=raw)
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `uv run pytest tests/slash/test_parser.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/slash/parser.py tests/slash/test_parser.py
git commit -m "feat(slash): parser with TOKEN/REST arg kinds"
```

---

## Task 3: Registry REST-last validation

**Files:**
- Modify: `src/poor_code/slash/registry.py`
- Modify: `tests/slash/test_registry.py`

- [ ] **Step 1: Add failing test**

Append to `tests/slash/test_registry.py`:

```python
from poor_code.slash.base import Arg, ArgKind


@dataclass
class _CmdWithArgs:
    name: str
    args: tuple
    description: str = "fake"
    def execute(self, ctx, parsed): pass


def test_rest_must_be_last_arg():
    bad = _CmdWithArgs(name="x", args=(
        Arg("body", ArgKind.REST),
        Arg("after", ArgKind.TOKEN),
    ))
    with pytest.raises(ValueError, match="REST.*last"):
        SlashRegistry([bad])


def test_rest_as_last_is_ok():
    ok = _CmdWithArgs(name="x", args=(
        Arg("name", ArgKind.TOKEN),
        Arg("body", ArgKind.REST),
    ))
    SlashRegistry([ok])  # no raise
```

- [ ] **Step 2: Run, expect failures (no validation yet)**

Run: `uv run pytest tests/slash/test_registry.py -v`
Expected: `test_rest_must_be_last_arg` fails (no ValueError raised).

- [ ] **Step 3: Add validation to `src/poor_code/slash/registry.py`**

Replace the entire file:

```python
from __future__ import annotations

from poor_code.slash.base import ArgKind, SlashCommand


class DuplicateSlashName(ValueError):
    pass


class SlashRegistry:
    def __init__(self, commands: list[SlashCommand]) -> None:
        by_name: dict[str, SlashCommand] = {}
        for c in commands:
            if c.name in by_name:
                raise DuplicateSlashName(c.name)
            self._validate_args(c)
            by_name[c.name] = c
        self._by_name = by_name

    @staticmethod
    def _validate_args(cmd: SlashCommand) -> None:
        args = getattr(cmd, "args", ())
        for i, a in enumerate(args):
            if a.kind is ArgKind.REST and i != len(args) - 1:
                raise ValueError(
                    f"command /{cmd.name}: REST arg '{a.name}' must be last"
                )

    def get(self, name: str) -> SlashCommand | None:
        return self._by_name.get(name)

    def all(self) -> list[SlashCommand]:
        return list(self._by_name.values())
```

- [ ] **Step 4: Run all slash tests, expect PASS**

Run: `uv run pytest tests/slash/ -v`
Expected: all previously-passing tests still pass + 2 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/poor_code/slash/registry.py tests/slash/test_registry.py
git commit -m "feat(slash): registry validates REST args are last"
```

---

## Task 4: Dispatcher

**Files:**
- Create: `src/poor_code/slash/dispatcher.py`
- Create: `tests/slash/fakes.py`
- Create: `tests/slash/test_dispatcher.py`

- [ ] **Step 1: Create fake `SlashContext` for tests**

Create `tests/slash/fakes.py`:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeSlashContext:
    notifications: list[tuple[str, str]] = field(default_factory=list)
    pushed_screens: list[Any] = field(default_factory=list)
    llms_set: list[Any] = field(default_factory=list)

    def push_screen(self, screen, callback=None):
        self.pushed_screens.append(screen)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((severity, message))

    def set_llm(self, llm) -> None:
        self.llms_set.append(llm)
```

- [ ] **Step 2: Write failing dispatcher tests**

Create `tests/slash/test_dispatcher.py`:

```python
from dataclasses import dataclass, field

from poor_code.slash.base import Arg, ArgKind, ParsedArgs
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.slash.registry import SlashRegistry
from tests.slash.fakes import FakeSlashContext


@dataclass
class _RecordingCmd:
    name: str = "login"
    description: str = "Sign in"
    args: tuple = ()
    calls: list[ParsedArgs] = field(default_factory=list)

    def execute(self, ctx, parsed: ParsedArgs) -> None:
        self.calls.append(parsed)


def test_dispatch_returns_false_for_non_slash_text():
    d = SlashDispatcher(SlashRegistry([_RecordingCmd()]))
    ctx = FakeSlashContext()
    assert d.dispatch("hello world", ctx) is False
    assert ctx.notifications == []


def test_dispatch_executes_matching_command():
    cmd = _RecordingCmd()
    d = SlashDispatcher(SlashRegistry([cmd]))
    ctx = FakeSlashContext()
    assert d.dispatch("/login", ctx) is True
    assert len(cmd.calls) == 1
    assert cmd.calls[0].values == {}


def test_dispatch_unknown_command_notifies_warning():
    d = SlashDispatcher(SlashRegistry([_RecordingCmd()]))
    ctx = FakeSlashContext()
    assert d.dispatch("/nope", ctx) is True
    assert ctx.notifications == [("warning", "unknown command: /nope")]


def test_dispatch_missing_arg_notifies_usage():
    cmd = _RecordingCmd(name="skill", args=(
        Arg("name", ArgKind.TOKEN),
        Arg("prompt", ArgKind.REST, optional=True),
    ))
    d = SlashDispatcher(SlashRegistry([cmd]))
    ctx = FakeSlashContext()
    assert d.dispatch("/skill", ctx) is True
    assert ctx.notifications == [
        ("warning", "missing arg: name — usage: /skill <name> [prompt]")
    ]
    assert cmd.calls == []


def test_registry_property_exposes_underlying_registry():
    reg = SlashRegistry([_RecordingCmd()])
    d = SlashDispatcher(reg)
    assert d.registry is reg
```

- [ ] **Step 3: Run, expect ImportError**

Run: `uv run pytest tests/slash/test_dispatcher.py -v`
Expected: ImportError on `poor_code.slash.dispatcher`.

- [ ] **Step 4: Implement dispatcher**

Create `src/poor_code/slash/dispatcher.py`:

```python
"""SlashDispatcher — try-handle pipeline for slash text.

Owns parse → execute → notify-on-error. Lets App.submit stay focused on
input dispatch + agent turn lifecycle.
"""
from __future__ import annotations

from poor_code.slash.base import SlashContext, usage_hint
from poor_code.slash.parser import MissingArg, UnknownCommand, parse
from poor_code.slash.registry import SlashRegistry


class SlashDispatcher:
    def __init__(self, registry: SlashRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> SlashRegistry:
        return self._registry

    def dispatch(self, text: str, ctx: SlashContext) -> bool:
        """Try to handle text as a slash command.
        Returns True if handled (executed or user-visible error)."""
        if not text.startswith("/"):
            return False
        try:
            name, parsed = parse(text, self._registry)
        except UnknownCommand as e:
            ctx.notify(f"unknown command: /{e.name}", severity="warning")
            return True
        except MissingArg as e:
            ctx.notify(
                f"missing arg: {e.arg.name} — usage: {usage_hint(e.cmd)}",
                severity="warning",
            )
            return True
        self._registry.get(name).execute(ctx, parsed)
        return True
```

- [ ] **Step 5: Run tests, expect PASS**

Run: `uv run pytest tests/slash/ -v`
Expected: all slash tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/poor_code/slash/dispatcher.py tests/slash/fakes.py tests/slash/test_dispatcher.py
git commit -m "feat(slash): SlashDispatcher with parse→execute→notify pipeline"
```

---

## Task 5: Migrate LoginCommand to new Protocol

**Files:**
- Modify: `src/poor_code/slash/commands/login.py`

- [ ] **Step 1: Update LoginCommand signature + add `args` field**

Replace the `LoginCommand` dataclass in `src/poor_code/slash/commands/login.py`:

```python
"""/login — opens a modal to configure a provider + API key + model.

On save: persists to auth_store, then swaps the running agent's LLM via
SlashContext.set_llm so the next turn uses the new credentials.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from poor_code.infra import auth_store
from poor_code.provider.client import LLMClient
from poor_code.provider.providers import ollama_cloud
from poor_code.slash.base import Arg, ParsedArgs, SlashContext
from poor_code.ui.screens.login import LoginResult, LoginScreen

_PROVIDERS: dict[str, Callable[..., LLMClient]] = {
    "ollama_cloud": ollama_cloud.configure,
}


def _build_llm(provider: str, *, model: str, api_key: str) -> LLMClient:
    factory = _PROVIDERS.get(provider)
    if factory is None:
        raise ValueError(f"unknown provider: {provider!r}")
    return factory(model=model, api_key=api_key)


@dataclass
class LoginCommand:
    name: str = "login"
    description: str = "Configure an LLM provider"
    args: tuple[Arg, ...] = field(default_factory=tuple)

    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None:
        def on_done(result: LoginResult) -> None:
            if result is None:
                return
            provider, model, api_key = result
            auth_store.save(provider, api_key=api_key, model=model)
            ctx.set_llm(_build_llm(provider, model=model, api_key=api_key))
            ctx.notify(f"signed in: {provider} ({model})")

        ctx.push_screen(LoginScreen(), on_done)
```

- [ ] **Step 2: Run all tests to check nothing broke**

Run: `uv run pytest -v 2>&1 | tail -40`
Expected: existing tests still pass except possibly `test_app_flow.py` (which Task 6 fixes if it broke). The `RunSlashCommand` path inside `app.py` still exists at this point — file compiles.

- [ ] **Step 3: Commit**

```bash
git add src/poor_code/slash/commands/login.py
git commit -m "refactor(slash): LoginCommand uses ParsedArgs signature"
```

---

## Task 6: Wire dispatcher into App + CLI

**Files:**
- Modify: `src/poor_code/app.py`
- Modify: `src/poor_code/cli.py`
- Test: `tests/ui/test_app_flow.py` (extend)

- [ ] **Step 1: Add failing integration test for dispatcher wiring**

Append to `tests/ui/test_app_flow.py`:

```python
from dataclasses import dataclass, field

from poor_code.slash.base import Arg, ArgKind, ParsedArgs
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.slash.registry import SlashRegistry


@dataclass
class _CallCounter:
    name: str = "ping"
    description: str = "test"
    args: tuple = ()
    seen: list[ParsedArgs] = field(default_factory=list)
    def execute(self, ctx, parsed): self.seen.append(parsed)


async def test_submit_slash_routes_through_dispatcher_not_agent():
    cmd = _CallCounter()
    slash = SlashDispatcher(SlashRegistry([cmd]))
    app = PoorCodeApp(agent=_agent_text("should-not-run"), slash=slash)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "p", "i", "n", "g")
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()

        assert len(cmd.seen) == 1
        assert cmd.seen[0].values == {}
        # No agent turn should have started.
        assert pilot.app.store.state.turns == []
```

- [ ] **Step 2: Run new test, expect FAIL**

Run: `uv run pytest tests/ui/test_app_flow.py::test_submit_slash_routes_through_dispatcher_not_agent -v`
Expected: either fails (executes through old code path) or `TypeError` from `PoorCodeApp.__init__` since `slash` isn't a `SlashDispatcher` yet.

- [ ] **Step 3: Rewrite `src/poor_code/app.py`**

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App
from textual.reactive import reactive

from poor_code.domain.agent import Agent
from poor_code.messages import SendPrompt
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.slash.registry import SlashRegistry
from poor_code.ui.screens.welcome import WelcomeScreen
from poor_code.ui.store import AppState, PromptSubmitted, Store


class PoorCodeApp(App):
    CSS_PATH = "ui/styles/app.tcss"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "cancel_or_quit", "Cancel/Quit"),
    ]

    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def __init__(self, agent: Agent, slash: SlashDispatcher | None = None) -> None:
        super().__init__()
        self.store = Store(AppState(cwd=str(Path.cwd())))
        self.agent = agent
        self.slash = slash or SlashDispatcher(SlashRegistry([]))
        self._cancel = asyncio.Event()

    def on_mount(self) -> None:
        self.store.subscribe(lambda s: setattr(self, "app_state", s))
        self.app_state = self.store.state
        self.push_screen(WelcomeScreen())

    def submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.slash.dispatch(text, ctx=self):
            return
        cmd = SendPrompt(text)
        self.store.dispatch(PromptSubmitted(cmd_id=cmd.cmd_id, user_text=text))
        self._cancel = asyncio.Event()
        self.run_worker(self._run_turn(cmd), group="turn", exclusive=True)

    async def _run_turn(self, cmd: SendPrompt) -> None:
        async for event in self.agent.run(cmd, self._cancel):
            self.store.dispatch(event)

    def set_llm(self, llm: Any) -> None:
        self.agent.llm = llm

    def action_cancel_or_quit(self) -> None:
        if self.app_state.is_processing:
            self._cancel.set()
        else:
            self.exit()
```

- [ ] **Step 4: Update `src/poor_code/cli.py`**

Replace the slash-registry line and import:

```python
# at top:
from poor_code.slash.dispatcher import SlashDispatcher

# in main():
def main() -> None:
    agent = _build_agent()
    slash = SlashDispatcher(SlashRegistry([LoginCommand()]))
    PoorCodeApp(agent=agent, slash=slash).run()
```

- [ ] **Step 5: Run all tests, expect PASS**

Run: `uv run pytest -v 2>&1 | tail -20`
Expected: full suite green, including the new dispatcher-wiring test.

- [ ] **Step 6: Commit**

```bash
git add src/poor_code/app.py src/poor_code/cli.py tests/ui/test_app_flow.py
git commit -m "refactor(app): submit delegates to SlashDispatcher"
```

---

## Task 7: PromptBox autocomplete widget

**Files:**
- Modify: `src/poor_code/ui/widgets/prompt_box.py` (full rewrite)
- Modify: `src/poor_code/ui/styles/app.tcss`
- Test: `tests/ui/test_prompt_box.py` (new)

- [ ] **Step 1: Add CSS rules for the popup**

Edit `src/poor_code/ui/styles/app.tcss`. Replace the existing `PromptBox` block:

```
PromptBox {
    dock: bottom;
    height: auto;
    border: round $accent;
    margin: 1 0;
    padding: 0 1;
}

PromptBox Input {
    background: transparent;
    border: none;
    padding: 0;
    height: 1;
}

#slash-suggest {
    max-height: 10;
    background: $surface;
    display: none;
    margin-bottom: 0;
}

#slash-suggest.visible {
    display: block;
}
```

- [ ] **Step 2: Write Pilot-driven tests**

Create `tests/ui/test_prompt_box.py`:

```python
from dataclasses import dataclass, field

from textual.widgets import Input, OptionList

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.slash.base import Arg, ArgKind, ParsedArgs
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.slash.registry import SlashRegistry
from tests.infra.fakes import (
    FakeContextLoader,
    FakeSettingsLoader,
    FakeSystemPromptComposer,
)
from tests.provider.fakes import FakeLLMClient


def _assembler() -> TurnAssembler:
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(),
        context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(),
        prompt_builder=PromptBuilder(),
    )


@dataclass
class _Cmd:
    name: str
    description: str
    args: tuple = ()
    seen: list[ParsedArgs] = field(default_factory=list)
    def execute(self, ctx, parsed): self.seen.append(parsed)


def _app_with(*cmds) -> PoorCodeApp:
    agent = Agent(
        llm=FakeLLMClient.text_only("nope"),
        tools=ToolRegistry([]),
        assembler=_assembler(),
    )
    slash = SlashDispatcher(SlashRegistry(list(cmds)))
    return PoorCodeApp(agent=agent, slash=slash)


async def test_typing_slash_shows_popup_with_all_commands():
    app = _app_with(_Cmd("login", "Sign in"), _Cmd("help", "Show help"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.display is True
        assert suggest.option_count == 2


async def test_typing_filters_by_prefix():
    app = _app_with(_Cmd("login", "Sign in"), _Cmd("help", "Show help"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l", "o")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.option_count == 1


async def test_whitespace_after_name_hides_popup():
    app = _app_with(_Cmd("login", "Sign in"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l", "o", "g", "i", "n", "space")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.display is False


async def test_no_matches_hides_popup():
    app = _app_with(_Cmd("login", "Sign in"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "z", "z", "z")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.display is False


async def test_tab_fills_input_and_hides_popup():
    cmd = _Cmd("login", "Sign in")
    app = _app_with(cmd)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        input_w = pilot.app.screen.query_one(Input)
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert input_w.value == "/login "
        assert suggest.display is False
        assert cmd.seen == []  # Tab does not execute


async def test_enter_on_no_arg_command_executes():
    cmd = _Cmd("login", "Sign in")
    app = _app_with(cmd)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(5):
            await pilot.pause()
        assert len(cmd.seen) == 1
        assert pilot.app.screen.query_one(Input).value == ""


async def test_enter_on_arg_command_fills_without_executing():
    cmd = _Cmd("skill", "Run a skill",
               args=(Arg("name", ArgKind.TOKEN), Arg("prompt", ArgKind.REST, optional=True)))
    app = _app_with(cmd)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        input_w = pilot.app.screen.query_one(Input)
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert input_w.value == "/skill "
        assert suggest.display is False
        assert cmd.seen == []


async def test_escape_hides_popup_preserves_input():
    app = _app_with(_Cmd("login", "Sign in"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l", "o")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.display is False
        assert pilot.app.screen.query_one(Input).value == "/lo"
```

- [ ] **Step 3: Run tests, expect FAILs (widget not built yet)**

Run: `uv run pytest tests/ui/test_prompt_box.py -v`
Expected: most tests fail with `NoMatches` on `#slash-suggest`, or wrong popup behavior.

- [ ] **Step 4: Rewrite `src/poor_code/ui/widgets/prompt_box.py`**

```python
from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from poor_code.slash.base import SlashCommand, usage_hint

_HINT_COL_WIDTH = 24


class PromptBox(Container):
    def __init__(self) -> None:
        super().__init__()
        self._filtered: list[SlashCommand] = []

    def compose(self) -> ComposeResult:
        yield OptionList(id="slash-suggest")
        yield Input(
            placeholder='Try "explain the philosophy in docs/"',
            id="prompt-input",
        )

    # --- input change → filter ---

    def on_input_changed(self, event: Input.Changed) -> None:
        value = event.value
        if not value.startswith("/") or " " in value:
            self._hide()
            return
        query = value[1:].lower()
        matches = sorted(
            (c for c in self._commands() if c.name.lower().startswith(query)),
            key=lambda c: c.name,
        )
        if not matches:
            self._hide()
            return
        self._show(matches)

    # --- key handling when popup open ---

    def on_key(self, event: Key) -> None:
        if not self._popup_open():
            return
        if event.key == "down":
            self._suggest().action_cursor_down()
            event.stop()
        elif event.key == "up":
            self._suggest().action_cursor_up()
            event.stop()
        elif event.key == "escape":
            self._hide()
            event.stop()
        elif event.key == "tab":
            self._apply_selection()
            event.stop()

    # --- submit ---

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        if not self._popup_open():
            text = event.value
            self.query_one(Input).value = ""
            self.app.submit(text)
            return
        cmd = self._highlighted_command()
        if cmd is None:
            text = event.value
            self.query_one(Input).value = ""
            self._hide()
            self.app.submit(text)
            return
        if cmd.args == ():
            self.query_one(Input).value = ""
            self._hide()
            self.app.submit(f"/{cmd.name}")
        else:
            self._apply_selection()

    # --- helpers ---

    def _commands(self) -> list[SlashCommand]:
        slash = getattr(self.app, "slash", None)
        if slash is None:
            return []
        return slash.registry.all()

    def _suggest(self) -> OptionList:
        return self.query_one("#slash-suggest", OptionList)

    def _popup_open(self) -> bool:
        return self._suggest().display and bool(self._filtered)

    def _show(self, matches: list[SlashCommand]) -> None:
        self._filtered = matches
        suggest = self._suggest()
        suggest.clear_options()
        for cmd in matches:
            label = Text()
            label.append(usage_hint(cmd).ljust(_HINT_COL_WIDTH))
            label.append("  ")
            label.append(cmd.description, style="dim")
            suggest.add_option(Option(label))
        suggest.highlighted = 0
        suggest.display = True

    def _hide(self) -> None:
        self._filtered = []
        suggest = self._suggest()
        suggest.clear_options()
        suggest.display = False

    def _highlighted_command(self) -> SlashCommand | None:
        idx = self._suggest().highlighted
        if idx is None or idx >= len(self._filtered):
            return None
        return self._filtered[idx]

    def _apply_selection(self) -> None:
        cmd = self._highlighted_command()
        if cmd is None:
            return
        input_w = self.query_one(Input)
        input_w.value = f"/{cmd.name} "
        input_w.cursor_position = len(input_w.value)
        self._hide()
```

- [ ] **Step 5: Run new tests, expect PASS**

Run: `uv run pytest tests/ui/test_prompt_box.py -v`
Expected: all 8 tests pass.

- [ ] **Step 6: Run full suite for regressions**

Run: `uv run pytest -v 2>&1 | tail -30`
Expected: full suite green.

- [ ] **Step 7: Commit**

```bash
git add src/poor_code/ui/widgets/prompt_box.py src/poor_code/ui/styles/app.tcss tests/ui/test_prompt_box.py
git commit -m "feat(ui): slash command autocomplete in PromptBox"
```

---

## Task 8: Manual verification

**Files:** none

- [ ] **Step 1: Launch app**

Run: `uv run poor-code`

- [ ] **Step 2: Verify each invariant from the spec**

Check, in this order:
1. Type `/` → popup appears with `/login` visible, `/login` description visible to the right.
2. Type `lo` (now `/lo`) → still shows `/login`.
3. Backspace twice to `/`, type `zzz` → popup hides (no matches).
4. Type `/login` then press `Tab` → input becomes `/login ` (trailing space), popup hides.
5. Clear input. Type `/` → popup shown. Press `Enter` → login modal opens (no-arg execution path).
6. Close login modal (Esc). Type `/`, press `Esc` while popup open → popup hides, input still `/`.
7. Type non-slash text (`hello`) → popup never appeared. Press Enter → message goes to agent path (or fails with no-auth message — expected).

If any step diverges from spec invariants, file an issue noting which invariant and the observed behavior, and STOP (do not silently patch).

- [ ] **Step 3: No commit needed unless fixes were made.**

---

## Self-Review

**Spec coverage check:**
- ✓ Component 1 (metadata model) → Task 1
- ✓ Component 2 (parser) → Task 2
- ✓ Component 3 (dispatcher) → Task 4
- ✓ Component 4 (autocomplete UI) → Task 7
- ✓ Component 5 (app wiring) → Task 6
- ✓ Component 6 (LoginCommand migration) → Task 5
- ✓ REST-last validation on registry → Task 3
- ✓ All test files listed in spec § Testing → Tasks 1–7
- ✓ Manual run verification → Task 8

**Placeholder scan:** none.

**Type consistency:** `SlashCommand.args: tuple[Arg, ...]` everywhere. `ParsedArgs.values: dict[str, str]` everywhere. `SlashDispatcher(SlashRegistry)` constructor unchanged across Tasks 4/6. `LoginCommand.args` uses `field(default_factory=tuple)` (dataclass safe) — `Arg(...)` type matches the Protocol.
