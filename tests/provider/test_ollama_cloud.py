import pytest

from poor_code.provider.auth import MissingApiKey
from poor_code.provider.client import LLMClient
from poor_code.provider.providers import ollama_cloud


def test_client_factory_requires_api_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with pytest.raises(MissingApiKey, match="OLLAMA_API_KEY"):
        ollama_cloud.client(model="qwen2.5-coder:7b")


def test_client_factory_builds_llm_client(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    client = ollama_cloud.client(model="qwen2.5-coder:7b")
    assert isinstance(client, LLMClient)
    assert client.model == "qwen2.5-coder:7b"
    assert client.base_url == "https://ollama.com"
    assert client.route.endpoint == "/v1/chat/completions"


def test_client_factory_accepts_custom_base_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    client = ollama_cloud.client(model="m", base_url="https://other.test")
    assert client.base_url == "https://other.test"
