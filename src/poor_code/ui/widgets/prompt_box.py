from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Key
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from poor_code.slash.base import SlashCommand, usage_hint
from poor_code.ui.store import AppState

_HINT_COL_WIDTH = 24

MascotMode = Literal["idle", "pending", "running"]

# 모든 프레임은 같은 셀 너비(6)로 통일 — border-top 문자열 흔들림 방지.
IDLE_FRAME = "(•‿•) "
PENDING_FRAMES = [
    "(˘_˘) ",
    "(¬_¬) ",
    "(-_-) ",
    "(-.-)z",
    "(O_O)!",
    "(°o°) ",
]
RUNNING_FRAMES = [
    "(ó_ò) ",
    "(°▽°) ",
    "(•‿•)*",
]


def compute_mascot_mode(state: AppState) -> MascotMode:
    if not state.is_processing:
        return "idle"
    if not state.turns:
        return "pending"
    last = state.turns[-1]
    return "running" if last.segments else "pending"


class PromptBox(Container):
    def __init__(self) -> None:
        super().__init__()
        self._filtered: list[SlashCommand] = []
        self._mascot_mode: MascotMode = "idle"
        self._mascot_index = 0
        self._mascot_timer = None

    def on_mount(self) -> None:
        self._original_placeholder = self.query_one(Input).placeholder
        self._cached_is_processing: bool | None = None
        self.border_title = IDLE_FRAME
        self.watch(self.app, "app_state", self._on_state_change)

    def _on_state_change(self, state: AppState) -> None:
        self._sync_placeholder(state)
        self._sync_mascot(state)

    def _sync_placeholder(self, state: AppState) -> None:
        key = (state.is_processing, getattr(state, "awaiting_input", False))
        if key == self._cached_is_processing:
            return
        self._cached_is_processing = key
        inp = self.query_one(Input)
        if state.awaiting_input:
            inp.placeholder = "답을 입력하세요"
        elif state.is_processing:
            inp.placeholder = "Ctrl+C로 취소"
        else:
            inp.placeholder = self._original_placeholder

    def _sync_mascot(self, state: AppState) -> None:
        new_mode = compute_mascot_mode(state)
        if new_mode == self._mascot_mode:
            return
        self._mascot_mode = new_mode
        self._mascot_index = 0
        self._apply_mascot_mode()

    def _apply_mascot_mode(self) -> None:
        self._stop_mascot_timer()
        if self._mascot_mode == "idle":
            self.border_title = IDLE_FRAME
            return
        frames = self._current_mascot_frames()
        self.border_title = frames[0]
        interval = 0.7 if self._mascot_mode == "pending" else 0.4
        self._mascot_timer = self.set_interval(interval, self._tick_mascot)

    def _current_mascot_frames(self) -> list[str]:
        if self._mascot_mode == "pending":
            return PENDING_FRAMES
        if self._mascot_mode == "running":
            return RUNNING_FRAMES
        return [IDLE_FRAME]

    def _tick_mascot(self) -> None:
        frames = self._current_mascot_frames()
        self._mascot_index = (self._mascot_index + 1) % len(frames)
        self.border_title = frames[self._mascot_index]

    def _stop_mascot_timer(self) -> None:
        if self._mascot_timer is not None:
            self._mascot_timer.stop()
            self._mascot_timer = None

    def on_unmount(self) -> None:
        self._stop_mascot_timer()

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
        st = self.app.app_state
        if st.is_processing and not getattr(st, "awaiting_input", False):
            return
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
