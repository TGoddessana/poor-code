import pytest

from poor_code.provider import providers
from poor_code.provider.client import LLMClient


def test_labels_include_both_providers():
    ids = [pid for pid, _ in providers.PROVIDER_LABELS]
    assert ids == ["ollama_cloud", "openai"]


def test_factories_cover_all_labels():
    assert set(providers.PROVIDER_FACTORIES) == {
        pid for pid, _ in providers.PROVIDER_LABELS
    }


def test_build_llm_dispatches_openai():
    client = providers.build_llm("openai", model="gpt-5.4-mini", api_key="sk-k")
    assert isinstance(client, LLMClient)
    assert client.base_url == "https://api.openai.com"
    assert client.model == "gpt-5.4-mini"


def test_build_llm_dispatches_ollama():
    client = providers.build_llm("ollama_cloud", model="gpt-oss:120b", api_key="k")
    assert client.base_url == "https://ollama.com"


def test_build_llm_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown provider"):
        providers.build_llm("nope", model="m", api_key="k")
