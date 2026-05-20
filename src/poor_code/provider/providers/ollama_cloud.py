"""Ollama Cloud — OpenAI Chat-compatible endpoint, Bearer auth.

Thin factory only: every poor-code Provider file should stay this small
(mirrors opencode's providers/*.ts pattern). Default model is overridable
at call site; do not hardcode here.
"""
from __future__ import annotations

from poor_code.provider.auth import BearerAuth
from poor_code.provider.client import LLMClient
from poor_code.provider.framing import SseFraming
from poor_code.provider.protocols.openai_chat import OpenAIChat
from poor_code.provider.route import Route

DEFAULT_BASE_URL = "https://ollama.com"


def client(model: str, base_url: str = DEFAULT_BASE_URL) -> LLMClient:
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth.from_env("OLLAMA_API_KEY"),
        framing=SseFraming(),
    )
    return LLMClient(route=route, base_url=base_url, model=model)
