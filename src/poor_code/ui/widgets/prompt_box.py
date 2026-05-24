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
            self._clear_input()
            self.app.submit(text)
            return
        cmd = self._highlighted_command()
        if cmd is None:
            text = event.value
            self._clear_input()
            self._hide()
            self.app.submit(text)
            return
        if not cmd.args:
            self._clear_input()
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

    def _clear_input(self) -> None:
        self.query_one(Input).value = ""

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
