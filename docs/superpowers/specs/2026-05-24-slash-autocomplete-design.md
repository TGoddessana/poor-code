# Slash Command Autocomplete + Metadata Model — Design

**Status:** draft
**Date:** 2026-05-24
**Scope:** Two interlocking changes — (1) a declarative argument-shape model on `SlashCommand`, (2) an in-input autocomplete popup in the chat UI driven by that model. Also includes a `SlashDispatcher` to keep `App.submit` focused on dispatch + turn lifecycle.

## Motivation

Today `/login` is the only slash command, and `App.submit` parses slash text inline with `text[1:].split()`. Two problems block the next step:

1. **No argument shape on commands.** Future commands (notably skill-as-command, e.g. `/skill <name> [free-form prompt]`) need to declare what they take so the parser knows when to stop tokenizing and the autocomplete UI can render a usage hint. Whitespace-splitting `/explain how does X work` into four tokens loses the natural-language argument.
2. **No discovery affordance.** Users have no way to learn what commands exist without reading source. Slash is meant to become the entry point for both built-in actions and skills, so this gets worse with scale.

This change addresses both: a small declarative arg schema on `SlashCommand`, and a popup that appears when input starts with `/` and shows matching commands with usage hints.

## Out of Scope

- Dynamic completion of argument positions (e.g. listing available skill names after `/skill `). Argument schema is used only for `usage hint` rendering and parser behavior in v1.
- Skill → slash-command adapter / contributor pattern. `SlashRegistry` stays a `list[SlashCommand]` injected at construction. Protocol is kept source-agnostic so adapters can be added later without breaking commands.
- Fuzzy matching. v1 uses case-insensitive prefix match on command name.
- Per-command keybinding hints in the popup.
- Visual layout overlays (z-layers). The popup grows the docked input box upward; ChatLog is allowed to be visually covered.

## Architecture

Three units, each with a single responsibility:

| Unit | File | Responsibility |
|---|---|---|
| Command metadata + parser | `slash/base.py`, `slash/parser.py` | Declare arg shape on commands. Parse raw text → `(name, ParsedArgs)`. Pure functions, no I/O. |
| Dispatcher | `slash/dispatcher.py` | Try-handle a text input as a slash command. Maps parser exceptions to `ctx.notify(...)`. Owns the parse→execute→notify pipeline. |
| Autocomplete UI | `ui/widgets/prompt_box.py`, `ui/styles/app.tcss` | Filter commands by current input, render popup with usage hints, handle keys (↑↓/Enter/Tab/Esc). |

`App.submit` becomes a dispatch site only: try slash, else spawn agent turn. `SlashRegistry` stays a pure `name → command` lookup.

## Component 1 — Command Metadata Model

**File:** `src/poor_code/slash/base.py` (rewritten)

```python
from enum import Enum
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable


class ArgKind(Enum):
    TOKEN = "token"   # one whitespace-delimited token
    REST  = "rest"    # entire remainder of line, raw (for natural language)


@dataclass(frozen=True)
class Arg:
    name: str
    kind: ArgKind
    optional: bool = False


@dataclass(frozen=True)
class ParsedArgs:
    values: dict[str, str]   # arg name → extracted string ("" if optional + missing)
    raw: str                 # full text after command name (preserved verbatim)


@runtime_checkable
class SlashContext(Protocol):
    def push_screen(self, screen: Any, callback: Callable[[Any], None] | None = None) -> Any: ...
    def notify(self, message: str, *, severity: str = "information") -> None: ...
    def set_llm(self, llm: Any) -> None: ...


@runtime_checkable
class SlashCommand(Protocol):
    name: str
    description: str
    args: tuple[Arg, ...]   # () for no-arg commands
    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None: ...


def usage_hint(cmd: SlashCommand) -> str:
    parts = [f"/{cmd.name}"]
    for a in cmd.args:
        parts.append(f"[{a.name}]" if a.optional else f"<{a.name}>")
    return " ".join(parts)
```

**Invariants:**
- A `REST` arg must be last in `args`. Constructing a command that violates this raises `ValueError` at registry-build time (`SlashRegistry.__init__` validates).
- `ParsedArgs.values` contains exactly one key per declared arg. Missing optional args map to `""`.
- Protocol is source-agnostic: a built-in `LoginCommand` and a future skill-derived adapter both satisfy it identically.

## Component 2 — Parser

**File:** `src/poor_code/slash/parser.py` (new)

```python
from dataclasses import dataclass
from poor_code.slash.base import ArgKind, ParsedArgs, SlashCommand
from poor_code.slash.registry import SlashRegistry


class UnknownCommand(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class MissingArg(Exception):
    def __init__(self, cmd: SlashCommand, arg) -> None:
        super().__init__(arg.name)
        self.cmd = cmd
        self.arg = arg


def parse(text: str, registry: SlashRegistry) -> tuple[str, ParsedArgs]:
    """text must start with '/'. Returns (name, ParsedArgs) or raises."""
    assert text.startswith("/")
    head, _, rest = text[1:].partition(" ")
    name = head
    cmd = registry.get(name)
    if cmd is None:
        raise UnknownCommand(name)
    rest = rest.strip()
    raw = rest
    values: dict[str, str] = {}
    for i, arg in enumerate(cmd.args):
        if arg.kind is ArgKind.REST:
            values[arg.name] = rest
            rest = ""
            break    # REST is validated last by SlashRegistry
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

**Decisions:**
- Trailing tokens after the last declared `TOKEN` arg are silently dropped. (Commands that need free-form input declare `REST`.)
- Empty `rest` for a required `TOKEN` → `MissingArg`. Dispatcher renders usage hint.
- REST-last validation lives on `SlashRegistry`, not the parser — parser trusts schemas it sees.

## Component 3 — Dispatcher

**File:** `src/poor_code/slash/dispatcher.py` (new)

```python
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
        Returns True if handled (either executed or user-visible error)."""
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

**Why a class, not a free function:** holds the registry reference (one less wiring parameter at call sites) and gives the autocomplete UI a single object to read commands from (`dispatcher.registry.all()`).

## Component 4 — Autocomplete UI

**File:** `src/poor_code/ui/widgets/prompt_box.py` (extended)

### Widget tree

```
PromptBox (Container, dock: bottom, height: auto)
├── OptionList #slash-suggest         (display: none by default)
└── Input      #prompt-input
```

`PromptBox` is `dock: bottom` + `height: auto`, so when `OptionList` becomes visible the box grows upward, visually covering the bottom of `ChatLog`. No overlay layer needed.

### Per-option rendering

```
/login                  Configure provider
/skill <name> [prompt]  Run a skill
```

Left column: `usage_hint(cmd)`. Right column: `cmd.description`. Built with `Text.assemble`, left column padded to a fixed width (e.g. 24), description truncated if too wide.

### State

- `_filtered: list[SlashCommand]` — current popup contents in display order. Used to resolve the highlighted `OptionList` index back to a command.
- Registry access: `self.app.slash.registry.all()` (dispatcher exposes registry; no constructor change needed).

### Filter — `on_input_changed`

```python
value = event.value
if not value.startswith("/"):
    self._hide(); return
if " " in value:               # past command name, into args
    self._hide(); return
query = value[1:].lower()
matches = sorted(
    [c for c in self._commands() if c.name.lower().startswith(query)],
    key=lambda c: c.name,
)
if not matches:
    self._hide(); return
self._show(matches)
```

- `value == "/"` → `query == ""` → all commands shown.
- First whitespace in input closes the popup (user is now typing args).

### Key handling

`PromptBox.on_key` (called before bubbling further):

| Key | Popup closed | Popup open |
|---|---|---|
| `up` / `down` | pass-through | move `OptionList.highlighted`, stop event |
| `escape` | pass-through | `_hide()`, stop event |
| `tab` | pass-through | `_apply_selection()`, stop event |
| (others) | pass-through | pass-through |

`PromptBox.on_input_submitted` (handles Enter):

```python
if not self._popup_open():
    self.app.submit(event.value)
    self._clear_input(); return
cmd = self._highlighted_command()
if cmd is None:                       # popup open but empty (shouldn't happen — hide guards it)
    self.app.submit(event.value); self._clear_input(); return
if cmd.args == ():
    self.app.submit(f"/{cmd.name}")   # round-trip through dispatcher → execute
    self._clear_input()
    self._hide()
else:
    self._apply_selection()   # fill input, leave for user to type args
```

`_apply_selection()`:
```python
input.value = f"/{cmd.name} "
input.cursor_position = len(input.value)
self._hide()
```

**Invariants:**
- Popup visibility is a pure function of current input value (`"/"` + no whitespace + matches exist). No hidden state across submissions.
- When popup is closed, all key/submit behavior is byte-identical to current behavior. Existing flows do not regress.
- Autocomplete reads command metadata only; adding/removing commands requires zero UI code changes.

### Styles — `app.tcss` additions

```
PromptBox {
    /* was: height: 3 */
    height: auto;
}
#slash-suggest {
    max-height: 10;
    border: round $accent;
    background: $surface;
    display: none;
}
#slash-suggest.visible { display: block; }
```

## Component 5 — App Wiring

**File:** `src/poor_code/app.py`

```python
def __init__(self, agent: Agent, slash: SlashDispatcher | None = None) -> None:
    ...
    self.slash = slash or SlashDispatcher(SlashRegistry([]))

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
```

`_route()` removed; `RunSlashCommand` import removed. The `RunSlashCommand` branch in `domain/agent.py:_cmd_to_text` becomes unreachable but is left in place — out of scope to delete.

**File:** `src/poor_code/cli.py`

```python
slash = SlashDispatcher(SlashRegistry([LoginCommand()]))
PoorCodeApp(agent=agent, slash=slash).run()
```

## Component 6 — Existing Command Migration

**File:** `src/poor_code/slash/commands/login.py`

```python
@dataclass
class LoginCommand:
    name: str = "login"
    description: str = "Configure an LLM provider"
    args: tuple[Arg, ...] = ()

    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None:
        # body unchanged — parsed.values is empty
        ...
```

Only the `args` field and the signature change. The body is untouched.

## Error Handling

- `UnknownCommand` → `ctx.notify("unknown command: /xyz", severity="warning")`. User sees a toast; popup is already closed (submission path).
- `MissingArg` → `ctx.notify("missing arg: <name> — usage: /skill <name> [prompt]", severity="warning")`.
- Parser/dispatcher never raise to `App.submit`. The only `False` return path is "not a slash command" (text does not start with `/`).
- Autocomplete UI does not surface parser errors — by construction, the popup only allows reaching `_apply_selection` (which never produces an error path) or `self.app.submit(...)` which goes through the dispatcher.

## Testing

| File | Status | Cases |
|---|---|---|
| `tests/slash/test_parser.py` | new | `/login` → values={}; `/skill foo bar baz` (TOKEN+REST) → values={name:'foo', prompt:'bar baz'}; `/skill` missing → `MissingArg`; `/skill foo` with optional REST → values={name:'foo', prompt:''}; `/unknown` → `UnknownCommand`; multiple spaces; trailing spaces. |
| `tests/slash/test_base.py` | new | `usage_hint(/login)` → `"/login"`; `usage_hint(/skill <n> [p])` → `"/skill <name> [prompt]"`. |
| `tests/slash/test_registry.py` | extend | REST-not-last validation raises at `SlashRegistry.__init__`. |
| `tests/slash/test_dispatcher.py` | new | `dispatch("hello", ctx)` → False; `dispatch("/login", ctx)` → True, command executed; `dispatch("/nope", ctx)` → True, `ctx.notify` called with "unknown"; `dispatch("/skill", ctx)` (missing arg) → True, `ctx.notify` called with usage. Uses a fake `SlashContext`. |
| `tests/ui/test_prompt_box.py` | new (Pilot) | (a) `/` typed → popup shown with all commands. (b) `/lo` → popup filtered to `login`. (c) `/login ` (trailing space) → popup hidden. (d) `↓` while open → highlighted index moves. (e) `Tab` on with-arg cmd → input=`/cmd `, popup hidden, no submit. (f) `Enter` on no-arg cmd → `App.submit` called once. (g) `Esc` → popup hidden, input preserved. |
| `tests/ui/test_app_flow.py` | extend | `submit("/login")` goes through dispatcher; existing free-text cases unchanged. |

Test fakes:
- `FakeSlashContext` in `tests/slash/fakes.py` (new): collects `notify` calls and `push_screen`/`set_llm` invocations.
- Pilot tests need a minimal `App` instance: reuse existing patterns from `tests/ui/test_app_flow.py`, but with a `SlashDispatcher` containing two test commands — one no-arg, one with `(TOKEN, REST optional)`.

## Migration Order

The change is one cohesive unit; suggested implementation order to minimize broken intermediate states:

1. `slash/base.py` rewrite + `slash/parser.py` + `slash/dispatcher.py` + parser/dispatcher tests.
2. `slash/registry.py` REST-last validation + test.
3. `LoginCommand` migration + `cli.py` wiring update + `app.py` simplification.
4. Run existing test suite; fix any fallout.
5. `PromptBox` autocomplete + styles + Pilot tests.
6. Manual run: launch app, type `/`, type `/lo`, Tab, Enter on no-arg, Esc — verify against this spec's invariants.

## Open Questions

None blocking. The following are intentionally deferred:
- Dynamic completion of argument positions (future spec).
- Skill-as-command adapter / contributor pattern (future spec).
- Whether dead `RunSlashCommand` branches should be removed (separate cleanup).
