"""Ollama Cloud — thin profile over openai_compatible.

Ollama Cloud exposes OpenAI-compatible /v1/chat/completions with Bearer auth.
All protocol/framing logic lives in openai_compatible.configure().
"""
from __future__ import annotations

from poor_code.provider.client import LLMClient
from poor_code.provider.providers import openai_compatible

BASE_URL = "https://ollama.com"


def configure(model: str, api_key: str, base_url: str = BASE_URL) -> LLMClient:
    return openai_compatible.configure(model=model, api_key=api_key, base_url=base_url)
