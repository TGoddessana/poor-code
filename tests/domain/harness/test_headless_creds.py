from poor_code.domain.harness import headless


def _clear(monkeypatch):
    for v in ("OLLAMA_API_KEY", "OPENAI_API_KEY", "POOR_CODE_API_KEY",
              "POOR_CODE_MODEL", "POOR_CODE_PROVIDER"):
        monkeypatch.delenv(v, raising=False)


def test_resolve_llm_prefers_env_defaults_to_ollama(monkeypatch):
    captured = {}

    def fake_build(provider, *, model, api_key):
        captured.update(provider=provider, model=model, api_key=api_key)
        return "LLM"

    _clear(monkeypatch)
    monkeypatch.setenv("OLLAMA_API_KEY", "k-env")
    monkeypatch.setenv("POOR_CODE_MODEL", "m-env")
    monkeypatch.setattr(headless, "build_llm", fake_build)
    monkeypatch.setattr(headless.auth_store, "get",
                        lambda _name: {"api_key": "k-disk", "model": "m-disk"})

    assert headless.resolve_llm() == "LLM"
    assert captured == {"provider": "ollama_cloud", "model": "m-env", "api_key": "k-env"}


def test_resolve_llm_selects_openai_provider_from_env(monkeypatch):
    captured = {}

    def fake_build(provider, *, model, api_key):
        captured.update(provider=provider, model=model, api_key=api_key)
        return "LLM"

    _clear(monkeypatch)
    monkeypatch.setenv("POOR_CODE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("POOR_CODE_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(headless, "build_llm", fake_build)

    assert headless.resolve_llm() == "LLM"
    assert captured == {"provider": "openai", "model": "gpt-5.4-mini", "api_key": "sk-env"}


def test_resolve_llm_falls_back_to_auth_store(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setattr(headless, "build_llm",
                        lambda provider, *, model, api_key: ("disk", provider, model, api_key))
    monkeypatch.setattr(headless.auth_store, "get",
                        lambda _name: {"api_key": "k-disk", "model": "m-disk"})
    assert headless.resolve_llm() == ("disk", "ollama_cloud", "m-disk", "k-disk")


def test_resolve_llm_returns_none_when_no_creds(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setattr(headless.auth_store, "get", lambda _name: None)
    assert headless.resolve_llm() is None
