from poor_code.provider.client import LLMClient
from poor_code.provider.providers import openai


def test_configure_builds_llm_client():
    client = openai.configure(model="gpt-5.4-mini", api_key="sk-test")
    assert isinstance(client, LLMClient)
    assert client.model == "gpt-5.4-mini"
    assert client.base_url == "https://api.openai.com"
    assert client.route.endpoint == "/v1/chat/completions"


def test_configure_sets_bearer_auth():
    client = openai.configure(model="m", api_key="sk-abc")
    headers: dict[str, str] = {}
    client.route.auth.apply(headers)
    assert headers["Authorization"] == "Bearer sk-abc"


def test_configure_sets_provider_display_name():
    client = openai.configure(model="m", api_key="k")
    assert client.provider_name == "openai"


def test_configure_enables_all_capabilities():
    client = openai.configure(model="m", api_key="k")
    caps = client.route.capabilities
    assert caps.response_format is True
    assert caps.tool_choice is True
    assert caps.parallel_tool_calls is True
    assert caps.strict_tools is True


def test_configure_accepts_custom_base_url():
    client = openai.configure(model="m", api_key="k", base_url="https://proxy.test")
    assert client.base_url == "https://proxy.test"


def test_configure_reads_call_timeout_from_env(monkeypatch):
    """Bench operators tune the per-call wall-clock budget without code changes."""
    monkeypatch.setenv("POOR_CODE_CALL_TIMEOUT", "90")
    client = openai.configure(model="m", api_key="k")
    assert client._call_timeout == 90.0


def test_configure_uses_default_call_timeout_without_env(monkeypatch):
    from poor_code.provider.client import DEFAULT_CALL_TIMEOUT
    monkeypatch.delenv("POOR_CODE_CALL_TIMEOUT", raising=False)
    client = openai.configure(model="m", api_key="k")
    assert client._call_timeout == DEFAULT_CALL_TIMEOUT
