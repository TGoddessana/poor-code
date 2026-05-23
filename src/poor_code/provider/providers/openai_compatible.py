"""Generic OpenAI-compatible provider factory.

Named providers (ollama_cloud, etc.) are thin profiles that call configure()
with a hardcoded base_url. This module owns the actual Route assembly.
"""
from __future__ import annotations

from poor_code.provider.auth import BearerAuth
from poor_code.provider.client import LLMClient
from poor_code.provider.framing import SseFraming
from poor_code.provider.protocols.openai_chat import OpenAICompatibleChat
from poor_code.provider.route import Route


def configure(model: str, api_key: str, base_url: str) -> LLMClient:
    route = Route(
        protocol=OpenAICompatibleChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token=api_key),
        framing=SseFraming(),
    )
    return LLMClient(route=route, base_url=base_url, model=model)
