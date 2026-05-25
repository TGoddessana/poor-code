from typing import Literal

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class ThinkingMascot(Widget):
    """마지막 TurnBlock 안에 마운트되어 에이전트 상태를 표정으로 표현."""

    DEFAULT_CSS = """
    ThinkingMascot {
        height: auto;
        margin-bottom: 1;
    }
    """

    PENDING_FRAMES = [" ( ˘_˘)", "(¬_¬) ", "(-_-) ", "(-_-) zZ", "(O_O)!", "(°o°) "]
    RUNNING_FRAMES = ["(ó_ò) ", "(ง •_•)ง", "(°▽°) "]

    def __init__(self, mode: Literal["pending", "running"]) -> None:
        super().__init__(classes="thinking-mascot")
        self._mode = mode
        self._frames = self.PENDING_FRAMES if mode == "pending" else self.RUNNING_FRAMES
        self._index = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Static(self._frames[0], classes="mascot-frame")

    def on_mount(self) -> None:
        interval = 0.7 if self._mode == "pending" else 0.4
        self._timer = self.set_interval(interval, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._index = (self._index + 1) % len(self._frames)
        self.query_one(".mascot-frame", Static).update(self._frames[self._index])
