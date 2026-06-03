"""Login modal — pick a provider, type a model id, paste an API key, save.

Result type: (provider_id, model, api_key) on save, or None on cancel.
When the API key field is left blank and the chosen provider already has
stored credentials, the stored key (and model, if model is blank) is reused —
this is how switching between configured providers works without re-pasting.
Persistence is handled by the caller (LoginCommand) via infra.auth_store.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from poor_code.infra import auth_store
from poor_code.provider.providers import PROVIDER_LABELS

PROVIDERS = PROVIDER_LABELS

LoginResult = tuple[str, str, str] | None


def default_provider_index(labels: list[tuple[str, str]], active: str | None) -> int:
    """Index of the active provider in `labels`, or 0 if active is unset/unknown."""
    for i, (pid, _) in enumerate(labels):
        if pid == active:
            return i
    return 0


def resolve_login(
    provider: str, model: str, key: str, *, stored: dict | None
) -> LoginResult:
    """Fill blank model/key from stored creds. None if either is still missing."""
    stored = stored or {}
    model = model or stored.get("model", "")
    key = key or stored.get("api_key", "")
    if not model or not key:
        return None
    return (provider, model, key)


class LoginScreen(ModalScreen[LoginResult]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        active = auth_store.get_active()
        default_idx = default_provider_index(PROVIDERS, active)
        with Vertical(id="login-box"):
            yield Static("Sign in", classes="login-title")
            yield Static("Provider:", classes="login-label")
            with RadioSet(id="login-providers"):
                for i, (pid, label) in enumerate(PROVIDERS):
                    yield RadioButton(label, value=(i == default_idx), id=f"prov-{pid}")
            yield Static("Model:", classes="login-label")
            yield Input(placeholder="model id (e.g. gpt-5.4-mini)", id="login-model")
            yield Static("API key:", classes="login-label")
            yield Input(
                placeholder="(saved — leave blank to keep)",
                password=True, id="login-key",
            )
            with Horizontal(id="login-buttons"):
                yield Button("Save", variant="primary", id="login-save")
                yield Button("Cancel", id="login-cancel")

    def on_mount(self) -> None:
        self._prefill_model(self._selected_provider())
        self.query_one("#login-model", Input).focus()

    def _prefill_model(self, provider: str) -> None:
        stored = auth_store.get(provider) or {}
        self.query_one("#login-model", Input).value = stored.get("model", "")

    def _selected_provider(self) -> str:
        rs = self.query_one("#login-providers", RadioSet)
        idx = rs.pressed_index if rs.pressed_index >= 0 else 0
        return PROVIDERS[idx][0]

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "login-providers":
            self._prefill_model(self._selected_provider())

    def _try_save(self) -> None:
        provider = self._selected_provider()
        model = self.query_one("#login-model", Input).value.strip()
        key = self.query_one("#login-key", Input).value.strip()
        resolved = resolve_login(provider, model, key, stored=auth_store.get(provider))
        if resolved is None:
            target = "#login-model" if not model else "#login-key"
            self.query_one(target, Input).focus()
            return
        self.dismiss(resolved)

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
