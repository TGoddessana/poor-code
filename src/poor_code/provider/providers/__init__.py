"""Provider registry — single source for provider id -> factory + display label.

cli.py (startup), slash/commands/login.py, and ui/screens/login.py all read
from here so the list of available providers lives in exactly one place.
"""
from __future__ import annotations

from typing import Callable

from poor_code.provider.client import LLMClient
from poor_code.provider.providers import ollama_cloud, openai

PROVIDER_FACTORIES: dict[str, Callable[..., LLMClient]] = {
    "ollama_cloud": ollama_cloud.configure,
    "openai": openai.configure,
}

# (id, display label) — also the radio order in the /login screen.
PROVIDER_LABELS: list[tuple[str, str]] = [
    ("ollama_cloud", "Ollama Cloud"),
    ("openai", "OpenAI"),
]


def build_llm(provider: str, *, model: str, api_key: str) -> LLMClient:
    factory = PROVIDER_FACTORIES.get(provider)
    if factory is None:
        raise ValueError(f"unknown provider: {provider!r}")
    return factory(model=model, api_key=api_key)
