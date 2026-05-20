"""Ollama native /api/chat protocol (NDJSON streaming, Bearer auth on cloud).

The Agent's history is OpenAI-shaped (assistant tool_calls carry id/type and a
stringified `arguments`); Ollama's wire format is different. build_body
translates here so the Agent never has to know which provider is on the other
end of the LLMClient.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, get_args

from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)


_REASON_ALIASES = set(get_args(FinishedReason.__dataclass_fields__["reason"].type))


class OllamaChat:
    def build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [_to_ollama_msg(m) for m in messages],
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        return body

    def for_stream(self) -> "_OllamaChatParser":
        return _OllamaChatParser()

    # OllamaChat() instances used at the Route level don't carry stream state;
    # parse_chunk on the bare protocol is intentionally unsupported — call
    # for_stream() to get a parser per request.


class _OllamaChatParser:
    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]:
        msg = chunk.get("message") or {}
        content = msg.get("content")
        if content:
            yield TextDelta(text=content)

        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            call_id = uuid.uuid4().hex
            args = fn.get("arguments")
            if args is None:
                args_json = "{}"
            elif isinstance(args, str):
                args_json = args
            else:
                args_json = json.dumps(args)
            yield ToolCallStarted(call_id=call_id, name=fn.get("name", ""))
            yield ToolCallInputDelta(call_id=call_id, json_delta=args_json)
            yield ToolCallEnded(call_id=call_id)

        if chunk.get("done"):
            reason = chunk.get("done_reason") or "stop"
            if reason not in _REASON_ALIASES:
                reason = "stop"
            yield FinishedReason(reason=reason)


def _to_ollama_msg(m: dict[str, Any]) -> dict[str, Any]:
    role = m.get("role")
    if role == "assistant":
        out: dict[str, Any] = {"role": "assistant", "content": m.get("content", "")}
        if calls := m.get("tool_calls"):
            out["tool_calls"] = [_translate_tool_call(tc) for tc in calls]
        return out
    if role == "tool":
        return {"role": "tool", "content": m.get("content", "")}
    return {"role": role, "content": m.get("content", "")}


def _translate_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    fn = tc.get("function") or {}
    raw_args = fn.get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            args = {}
    else:
        args = raw_args
    return {"function": {"name": fn.get("name", ""), "arguments": args}}
