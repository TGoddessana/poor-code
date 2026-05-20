"""Ollama Cloud — native /api/chat endpoint, Bearer auth.

Thin factory only: every poor-code Provider file should stay this small
(mirrors opencode's providers/*.ts pattern). API key is provided explicitly
by the caller; persistence lives in infra.auth_store, not here.

Ollama Cloud does NOT expose the OpenAI-compatible /v1/chat/completions
endpoint — that one only exists on local Ollama. Cloud only speaks the native
Ollama API with NDJSON streaming.
"""
from __future__ import annotations

from poor_code.provider.auth import BearerAuth
from poor_code.provider.client import LLMClient
from poor_code.provider.framing import NdjsonFraming
from poor_code.provider.protocols.ollama_chat import OllamaChat
from poor_code.provider.route import Route

DEFAULT_BASE_URL = "https://ollama.com"


def client(model: str, api_key: str, base_url: str = DEFAULT_BASE_URL) -> LLMClient:
    route = Route(
        protocol=OllamaChat(),
        endpoint="/api/chat",
        auth=BearerAuth(token=api_key),
        framing=NdjsonFraming(),
    )
    return LLMClient(route=route, base_url=base_url, model=model)
