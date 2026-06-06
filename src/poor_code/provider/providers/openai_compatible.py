"""Generic OpenAI-compatible provider factory.

Named providers (ollama_cloud, etc.) are thin profiles that call configure()
with a hardcoded base_url. This module owns the actual Route assembly.
"""
from __future__ import annotations

import os

from poor_code.provider.auth import BearerAuth
from poor_code.provider.capabilities import Capabilities
from poor_code.provider.client import LLMClient
from poor_code.provider.framing import SseFraming
from poor_code.provider.protocols.openai_chat import OpenAICompatibleChat
from poor_code.provider.route import Route


def configure(
    model: str, api_key: str, base_url: str, provider_name: str = "",
    capabilities: Capabilities = Capabilities(),
) -> LLMClient:
    route = Route(
        protocol=OpenAICompatibleChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token=api_key),
        framing=SseFraming(),
        capabilities=capabilities,
    )
    kwargs = {}
    # Per-call wall-clock budget override (bench tuning). Invalid values fall back
    # to the LLMClient default rather than crashing provider construction.
    env_timeout = os.environ.get("POOR_CODE_CALL_TIMEOUT")
    if env_timeout:
        try:
            kwargs["call_timeout"] = float(env_timeout)
        except ValueError:
            pass
    return LLMClient(
        route=route, base_url=base_url, model=model, provider_name=provider_name,
        **kwargs,
    )
