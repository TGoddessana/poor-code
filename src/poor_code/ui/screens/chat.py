import shutil
import subprocess
import sys

from textual import events
from textual.app import ComposeResult
from textual.geometry import Offset
from textual.screen import Screen
from textual.widget import Widget

from poor_code.ui.widgets.chat_log import ChatLog
from poor_code.ui.widgets.prompt_box import PromptBox
from poor_code.ui.widgets.status_footer import StatusFooter
from poor_code.ui.widgets.stepper import StepperBar


def _copy_to_system_clipboard(text: str) -> bool:
    # OSC 52 (Textual's default) gets swallowed by tmux and some terminals.
    # Shell out to the native helper instead.
    if sys.platform == "darwin":
        cmd = ["pbcopy"]
    elif sys.platform.startswith("linux"):
        if shutil.which("wl-copy"):
            cmd = ["wl-copy"]
        elif shutil.which("xclip"):
            cmd = ["xclip", "-selection", "clipboard"]
        elif shutil.which("xsel"):
            cmd = ["xsel", "--clipboard", "--input"]
        else:
            return False
    else:
        return False
    try:
        subprocess.run(cmd, input=text.encode("utf-8"), check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


class ChatScreen(Screen):
    def compose(self) -> ComposeResult:
        yield StepperBar(id="stepper-bar")
        yield ChatLog(id="chat-log")
        yield PromptBox()
        yield StatusFooter(id="status-footer")

    def get_widget_and_offset_at(
        self, x: int, y: int
    ) -> tuple[Widget | None, Offset | None]:
        # Workaround for Textual 8.2.6+ regression: during a drag, the compositor
        # can return the screen itself when the mouse hits an empty area, which
        # then trips an unguarded `assert isinstance(content_widget.parent, Widget)`
        # in Screen._forward_event. Screen.parent is the App (not a Widget), so
        # treat "self" hits as "no widget" to skip that path.
        widget, offset = super().get_widget_and_offset_at(x, y)
        if widget is self:
            return None, None
        return widget, offset

    def on_text_selected(self, event: events.TextSelected) -> None:
        selection = self.get_selected_text()
        if not selection:
            return
        if _copy_to_system_clipboard(selection):
            self.notify(f"Copied {len(selection)} chars", timeout=1.5)
        else:
            # Last-resort fallback: OSC 52 (works on iTerm2/Ghostty without tmux,
            # or with `tmux set -g set-clipboard on` + a compliant outer term).
            self.app.copy_to_clipboard(selection)
            self.notify("Copy via OSC 52 (terminal may block)", timeout=1.5)
