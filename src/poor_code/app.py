from textual.app import App

from poor_code.ui.screens.welcome import WelcomeScreen


class PoorCodeApp(App):
    CSS_PATH = "ui/styles/app.tcss"
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())
