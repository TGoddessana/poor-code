from poor_code.provider.client import LLMClient
from poor_code.provider.providers import ollama_cloud


def test_client_factory_builds_llm_client():
    client = ollama_cloud.client(model="gpt-oss:120b", api_key="test-key")
    assert isinstance(client, LLMClient)
    assert client.model == "gpt-oss:120b"
    assert client.base_url == "https://ollama.com"
    assert client.route.endpoint == "/api/chat"


def test_client_factory_accepts_custom_base_url():
    client = ollama_cloud.client(model="m", api_key="k", base_url="https://other.test")
    assert client.base_url == "https://other.test"


def test_client_factory_sets_bearer_auth():
    client = ollama_cloud.client(model="m", api_key="abc")
    headers: dict[str, str] = {}
    client.route.auth.apply(headers)
    assert headers["Authorization"] == "Bearer abc"
