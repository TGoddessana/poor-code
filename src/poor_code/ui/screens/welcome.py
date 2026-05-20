from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static

from poor_code.ui.widgets.banner import Banner
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
        yield PromptBox()
