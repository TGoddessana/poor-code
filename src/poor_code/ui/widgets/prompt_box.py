from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Input


class PromptBox(Container):
    def compose(self) -> ComposeResult:
        yield Input(
            placeholder='Try "explain the philosophy in docs/"',
            id="prompt-input",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value
        self.query_one(Input).value = ""
        self.app.submit(text)
