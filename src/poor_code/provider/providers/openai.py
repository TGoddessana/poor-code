"""OpenAI — thin profile over openai_compatible.

OpenAI's /v1/chat/completions honors response_format (json_schema),
tool_choice, parallel_tool_calls, and per-function strict tools, so all
capabilities are enabled. Protocol/framing logic lives in
openai_compatible.configure().
"""
from __future__ import annotations

from poor_code.provider.capabilities import Capabilities
from poor_code.provider.client import LLMClient
from poor_code.provider.providers import openai_compatible

BASE_URL = "https://api.openai.com"


def configure(model: str, api_key: str, base_url: str = BASE_URL) -> LLMClient:
    return openai_compatible.configure(
        model=model, api_key=api_key, base_url=base_url,
        provider_name="openai",
        capabilities=Capabilities(
            response_format=True,
            tool_choice=True,
            parallel_tool_calls=True,
            strict_tools=True,
        ),
    )
