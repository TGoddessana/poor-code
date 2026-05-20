"""OpenAI Chat-Completions streaming protocol.

Covers all OpenAI-compatible endpoints: OpenAI itself, Ollama (cloud + local
`/v1/chat/completions`), llama.cpp `llama-server`, DeepSeek, Groq, Together,
xAI, OpenRouter, etc. Adding any of those means a new `providers/<name>.py`
that reuses this Protocol with a different baseURL.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Protocol as _PyProtocol

from poor_code.provider.events import LLMEvent


class Protocol(_PyProtocol):
    def build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]: ...

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]: ...


class OpenAIChat:
    def build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        return body

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
        # Implemented in Task 7.
        raise NotImplementedError
