"""OpenAI Chat-Completions streaming protocol.

Covers all OpenAI-compatible endpoints: OpenAI itself, Ollama (cloud + local
`/v1/chat/completions`), llama.cpp `llama-server`, DeepSeek, Groq, Together,
xAI, OpenRouter, etc. Adding any of those means a new `providers/<name>.py`
that reuses this Protocol with a different baseURL.
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol as _PyProtocol

from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)


class Protocol(_PyProtocol):
    def build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]: ...

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]: ...


class OpenAIChat:
    """Stateless across requests; the per-stream parse state lives on the
    instance returned by `for_stream()`. The bare `OpenAIChat()` instance
    used in build_body shares no state — clients call `for_stream()` once
    per HTTP request to get a fresh parser.
    """

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

    # parse_chunk holds per-stream state (index → call_id, open call order).
    # Callers should construct one OpenAIChat per stream OR call for_stream()
    # to get an isolated parser.
    def __init__(self) -> None:
        self._index_to_call: dict[int, str] = {}
        self._open_order: list[str] = []

    def for_stream(self) -> "OpenAIChat":
        return OpenAIChat()

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
        choices = chunk.get("choices") or []
        if not choices:
            return
        choice = choices[0]
        delta = choice.get("delta") or {}

        content = delta.get("content")
        if content:
            yield TextDelta(text=content)

        for tc in delta.get("tool_calls") or []:
            index = tc.get("index")
            fn = tc.get("function") or {}
            call_id = tc.get("id")
            name = fn.get("name")
            args = fn.get("arguments")

            if index is not None and call_id and name is not None and index not in self._index_to_call:
                # First chunk for this index: registers the call.
                self._index_to_call[index] = call_id
                self._open_order.append(call_id)
                yield ToolCallStarted(call_id=call_id, name=name)
                if args:
                    yield ToolCallInputDelta(call_id=call_id, json_delta=args)
                continue

            # Continuation chunk: argument delta only.
            if index is not None and index in self._index_to_call and args:
                yield ToolCallInputDelta(
                    call_id=self._index_to_call[index], json_delta=args
                )

        finish = choice.get("finish_reason")
        if finish:
            for call_id in self._open_order:
                yield ToolCallEnded(call_id=call_id)
            self._open_order.clear()
            yield FinishedReason(reason=finish)
