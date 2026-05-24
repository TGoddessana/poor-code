from textual.app import ComposeResult
from textual.screen import Screen

from poor_code.ui.widgets.chat_log import ChatLog
from poor_code.ui.widgets.prompt_box import PromptBox


class ChatScreen(Screen):
    def compose(self) -> ComposeResult:
        yield ChatLog(id="chat-log")
        yield PromptBox()
