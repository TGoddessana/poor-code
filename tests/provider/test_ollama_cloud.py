from poor_code.provider.client import LLMClient
from poor_code.provider.providers import ollama_cloud


def test_configure_builds_llm_client():
    client = ollama_cloud.configure(model="gpt-oss:120b", api_key="test-key")
    assert isinstance(client, LLMClient)
    assert client.model == "gpt-oss:120b"
    assert client.base_url == "https://ollama.com"
    assert client.route.endpoint == "/v1/chat/completions"


def test_configure_accepts_custom_base_url():
    client = ollama_cloud.configure(model="m", api_key="k", base_url="https://other.test")
    assert client.base_url == "https://other.test"


def test_configure_sets_bearer_auth():
    client = ollama_cloud.configure(model="m", api_key="abc")
    headers: dict[str, str] = {}
    client.route.auth.apply(headers)
    assert headers["Authorization"] == "Bearer abc"
