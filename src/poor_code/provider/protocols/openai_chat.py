"""OpenAI-compatible /v1/chat/completions streaming protocol.

Messages are passed through unchanged (already OpenAI-shaped).
Tool call arguments are streamed token-by-token by OpenAI; the parser
accumulates them and emits Started+InputDelta+Ended on finish_reason.
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable

from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)

_VALID_REASONS = {"stop", "tool_calls", "length", "error"}


class OpenAICompatibleChat:
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

    def for_stream(self) -> "_OpenAIChatParser":
        return _OpenAIChatParser()


class _OpenAIChatParser:
    def __init__(self) -> None:
        self._calls: dict[int, dict[str, str]] = {}

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
        choices = chunk.get("choices") or []
        if not choices:
            return

        choice = choices[0]
        delta = choice.get("delta") or {}
        finish_reason = choice.get("finish_reason")

        content = delta.get("content")
        if content:
            yield TextDelta(text=content)

        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            if idx not in self._calls:
                self._calls[idx] = {"id": tc.get("id") or "", "name": "", "args": ""}
            call = self._calls[idx]
            fn = tc.get("function") or {}
            if fn.get("name"):
                call["name"] = fn["name"]
            if fn.get("arguments"):
                call["args"] += fn["arguments"]

        if finish_reason is not None:
            for idx in sorted(self._calls):
                call = self._calls[idx]
                call_id = call["id"] or uuid.uuid4().hex
                yield ToolCallStarted(call_id=call_id, name=call["name"])
                yield ToolCallInputDelta(call_id=call_id, json_delta=call["args"] or "{}")
                yield ToolCallEnded(call_id=call_id)
            reason = finish_reason if finish_reason in _VALID_REASONS else "stop"
            yield FinishedReason(reason=reason)
