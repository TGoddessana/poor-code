from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen

from poor_code.ui.widgets.banner import Banner
from poor_code.ui.widgets.chat_log import ChatLog
from poor_code.ui.widgets.prompt_box import PromptBox


class WelcomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Banner()
        yield ChatLog(id="chat-log")
        yield PromptBox()
