"""OpenAI-compatible /v1/chat/completions streaming protocol.

Messages are passed through unchanged (already OpenAI-shaped).
Tool call arguments are streamed token-by-token by OpenAI; the parser
accumulates them and emits Started+InputDelta+Ended on finish_reason.
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable

from poor_code.provider.capabilities import Capabilities
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
    UsageEnded,
)

_VALID_REASONS = {"stop", "tool_calls", "length", "error"}


class OpenAICompatibleChat:
    def build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        *,
        capabilities: Capabilities = Capabilities(),
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
        if response_format is not None and capabilities.response_format:
            body["response_format"] = response_format
        return body

    def for_stream(self) -> "_OpenAIChatParser":
        return _OpenAIChatParser()


class _OpenAIChatParser:
    """Accumulates streamed tool calls.

    Calls are keyed by `id`, not by `index`. The OpenAI spec distinguishes
    parallel tool calls by `index`, but some providers (e.g. ollama.com's
    minimax-m3) emit every parallel call with `index: 0`, distinguishing them
    only by `id`. Keying by index there merges two individually-valid argument
    payloads into one invalid blob (`{"path":"a"}{"path":"b"}`), which the server
    later rejects with HTTP 400. Standard streaming sends `id` only on a call's
    first chunk and id-less continuation chunks carry only `index`; we map those
    back to the in-progress call via `index → key`.
    """

    def __init__(self) -> None:
        self._calls: dict[str, dict[str, str]] = {}
        self._order: list[str] = []
        self._index_to_key: dict[int, str] = {}

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
        # OpenAI's final-chunk usage frame has choices=[] (or absent) and
        # usage populated. Emit UsageEnded before bailing on no-choices.
        usage = chunk.get("usage")
        if usage:
            details = usage.get("prompt_tokens_details") or {}
            yield UsageEnded(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                cached_input_tokens=details.get("cached_tokens", 0) or 0,
            )
        elif chunk.get("done") and (
            chunk.get("prompt_eval_count") is not None
            or chunk.get("eval_count") is not None
        ):
            # Ollama native shape — no OpenAI `usage` field; fall back to its
            # own eval counts. Only triggers when the OpenAI shape is absent.
            yield UsageEnded(
                input_tokens=chunk.get("prompt_eval_count") or 0,
                output_tokens=chunk.get("eval_count") or 0,
            )

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
            tcid = tc.get("id") or ""
            if tcid:
                # A non-empty id starts (or re-selects) a call. Distinct ids at
                # the same index → distinct calls (the minimax case).
                key = tcid
                if key not in self._calls:
                    self._calls[key] = {"id": tcid, "name": "", "args": ""}
                    self._order.append(key)
                self._index_to_key[idx] = key
            else:
                # id-less continuation chunk — belongs to the call in progress at
                # this index (standard OpenAI argument streaming).
                key = self._index_to_key.get(idx)
                if key is None:
                    key = f"__idx_{idx}"
                    self._calls[key] = {"id": "", "name": "", "args": ""}
                    self._order.append(key)
                    self._index_to_key[idx] = key
            call = self._calls[key]
            fn = tc.get("function") or {}
            if fn.get("name"):
                call["name"] = fn["name"]
            if fn.get("arguments"):
                call["args"] += fn["arguments"]

        if finish_reason is not None:
            for key in self._order:
                call = self._calls[key]
                cid = call["id"] or uuid.uuid4().hex
                yield ToolCallStarted(call_id=cid, name=call["name"])
                yield ToolCallInputDelta(call_id=cid, json_delta=call["args"] or "{}")
                yield ToolCallEnded(call_id=cid)
            reason = finish_reason if finish_reason in _VALID_REASONS else "stop"
            yield FinishedReason(reason=reason)
