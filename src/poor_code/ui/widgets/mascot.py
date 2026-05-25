"""Global ThinkingMascot — ChatScreen 하단의 처리 상태 인디케이터.

app.app_state를 watch하여 idle / pending / running 세 모드를 자체 결정.
"""
from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from poor_code.ui.store import AppState

Mode = Literal["idle", "pending", "running"]


class ThinkingMascot(Widget):
    """글로벌 처리 상태 인디케이터. PromptBox 바로 위에 docked."""

    DEFAULT_CSS = """
    ThinkingMascot {
        height: 1;
    }
    """

    IDLE_FRAME = "(•‿•)"
    PENDING_FRAMES = [" ( ˘_˘)", "(¬_¬) ", "(-_-) ", "(-_-) zZ", "(O_O)!", "(°o°) "]
    RUNNING_FRAMES = ["(ó_ò) ", "(ง •_•)ง", "(°▽°) "]

    def __init__(self) -> None:
        super().__init__(classes="thinking-mascot")
        self._mode: Mode = "idle"
        self._index = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Static(self.IDLE_FRAME, classes="mascot-frame")

    def on_mount(self) -> None:
        self.watch(self.app, "app_state", self._on_state_change)

    def on_unmount(self) -> None:
        self._stop_timer()

    def _on_state_change(self, state: AppState) -> None:
        new_mode = self._compute_mode(state)
        if new_mode == self._mode:
            return
        self._mode = new_mode
        self._index = 0
        self._apply_mode()

    @staticmethod
    def _compute_mode(state: AppState) -> Mode:
        if not state.is_processing:
            return "idle"
        if not state.turns:
            return "pending"
        last = state.turns[-1]
        return "running" if last.segments else "pending"

    def _apply_mode(self) -> None:
        self._stop_timer()
        if self._mode == "idle":
            self._set_frame(self.IDLE_FRAME)
            return
        frames = self._current_frames()
        self._set_frame(frames[0])
        interval = 0.7 if self._mode == "pending" else 0.4
        self._timer = self.set_interval(interval, self._tick)

    def _current_frames(self) -> list[str]:
        if self._mode == "pending":
            return self.PENDING_FRAMES
        if self._mode == "running":
            return self.RUNNING_FRAMES
        return [self.IDLE_FRAME]

    def _set_frame(self, text: str) -> None:
        self.query_one(".mascot-frame", Static).update(text)

    def _tick(self) -> None:
        if self._mode == "idle":
            return
        frames = self._current_frames()
        self._index = (self._index + 1) % len(frames)
        self._set_frame(frames[self._index])

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
