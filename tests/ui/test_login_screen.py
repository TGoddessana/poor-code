import pytest

from poor_code.infra import auth_store
from poor_code.ui.screens.login import (
    PROVIDERS,
    LoginScreen,
    default_provider_index,
    resolve_login,
)


# --- resolve_login: fills blanks from stored creds, else None ---

def test_resolve_uses_typed_values_when_present():
    assert resolve_login("openai", "gpt-5.4-mini", "sk-typed", stored=None) == (
        "openai", "gpt-5.4-mini", "sk-typed")


def test_resolve_reuses_stored_key_when_key_blank():
    stored = {"api_key": "sk-stored", "model": "gpt-old"}
    assert resolve_login("openai", "gpt-5.4-mini", "", stored=stored) == (
        "openai", "gpt-5.4-mini", "sk-stored")


def test_resolve_reuses_stored_model_when_model_blank():
    stored = {"api_key": "sk-stored", "model": "gpt-old"}
    assert resolve_login("openai", "", "", stored=stored) == (
        "openai", "gpt-old", "sk-stored")


def test_resolve_none_when_no_key_anywhere():
    assert resolve_login("openai", "gpt-5.4-mini", "", stored=None) is None


def test_resolve_none_when_no_model_anywhere():
    assert resolve_login("openai", "", "sk-typed", stored={"api_key": "x"}) is None


# --- default_provider_index: which radio is pre-selected ---

LABELS = [("ollama_cloud", "Ollama Cloud"), ("openai", "OpenAI")]


def test_default_index_is_active_provider():
    assert default_provider_index(LABELS, "openai") == 1


def test_default_index_zero_when_active_none():
    assert default_provider_index(LABELS, None) == 0


def test_default_index_zero_when_active_unknown():
    assert default_provider_index(LABELS, "ghost") == 0


from textual.app import App
from textual.widgets import Input, RadioSet


class _Host(App):
    def compose(self):
        return []


async def test_screen_prefills_active_provider_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_store.Path, "home", classmethod(lambda cls: tmp_path))
    auth_store.save("ollama_cloud", api_key="a", model="m1")
    auth_store.save("openai", api_key="sk", model="gpt-5.4-mini")  # active = openai

    app = _Host()
    async with app.run_test() as pilot:
        screen = LoginScreen()
        result_holder = []
        app.push_screen(screen, result_holder.append)
        await pilot.pause()

        # Active provider (openai) is pre-selected.
        rs = screen.query_one("#login-providers", RadioSet)
        assert PROVIDERS[rs.pressed_index][0] == "openai"
        # Its stored model is pre-filled.
        assert screen.query_one("#login-model", Input).value == "gpt-5.4-mini"
