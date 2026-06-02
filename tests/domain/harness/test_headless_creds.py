from poor_code.domain.harness import headless


def test_resolve_llm_prefers_env(monkeypatch):
    captured = {}

    def fake_configure(*, model, api_key):
        captured["model"] = model
        captured["api_key"] = api_key
        return "LLM"

    monkeypatch.setenv("OLLAMA_API_KEY", "k-env")
    monkeypatch.setenv("POOR_CODE_MODEL", "m-env")
    monkeypatch.setattr(headless.ollama_cloud, "configure", fake_configure)
    monkeypatch.setattr(headless.auth_store, "get", lambda _name: {"api_key": "k-disk", "model": "m-disk"})

    llm = headless.resolve_llm()
    assert llm == "LLM"
    assert captured == {"model": "m-env", "api_key": "k-env"}


def test_resolve_llm_falls_back_to_auth_store(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("POOR_CODE_MODEL", raising=False)
    monkeypatch.setattr(headless.ollama_cloud, "configure", lambda *, model, api_key: ("disk", model, api_key))
    monkeypatch.setattr(headless.auth_store, "get", lambda _name: {"api_key": "k-disk", "model": "m-disk"})
    assert headless.resolve_llm() == ("disk", "m-disk", "k-disk")


def test_resolve_llm_returns_none_when_no_creds(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("POOR_CODE_MODEL", raising=False)
    monkeypatch.setattr(headless.auth_store, "get", lambda _name: None)
    assert headless.resolve_llm() is None
