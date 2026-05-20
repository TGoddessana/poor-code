"""Login modal — pick a provider, type a model id, paste an API key, save.

Result type: (provider_id, model, api_key) on save, or None on cancel.
Persistence is handled by the caller (a SlashCommand) via infra.auth_store.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, RadioButton, RadioSet, Static


PROVIDERS = [
    ("ollama_cloud", "Ollama Cloud"),
]


LoginResult = tuple[str, str, str] | None


class LoginScreen(ModalScreen[LoginResult]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Static("Sign in", classes="login-title")
            yield Static("Provider:", classes="login-label")
            with RadioSet(id="login-providers"):
                for i, (pid, label) in enumerate(PROVIDERS):
                    yield RadioButton(label, value=(i == 0), id=f"prov-{pid}")
            yield Static("Model:", classes="login-label")
            yield Input(placeholder="model id (e.g. gpt-oss:120b)", id="login-model")
            yield Static("API key:", classes="login-label")
            yield Input(placeholder="paste your key…", password=True, id="login-key")
            with Horizontal(id="login-buttons"):
                yield Button("Save", variant="primary", id="login-save")
                yield Button("Cancel", id="login-cancel")

    def on_mount(self) -> None:
        self.query_one("#login-model", Input).focus()

    def _selected_provider(self) -> str:
        rs = self.query_one("#login-providers", RadioSet)
        idx = rs.pressed_index if rs.pressed_index >= 0 else 0
        return PROVIDERS[idx][0]

    def _try_save(self) -> None:
        model = self.query_one("#login-model", Input).value.strip()
        key = self.query_one("#login-key", Input).value.strip()
        if not model:
            self.query_one("#login-model", Input).focus()
            return
        if not key:
            self.query_one("#login-key", Input).focus()
            return
        self.dismiss((self._selected_provider(), model, key))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "login-save":
            self._try_save()
        elif event.button.id == "login-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "login-key":
            self._try_save()
        elif event.input.id == "login-model":
            self.query_one("#login-key", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)
