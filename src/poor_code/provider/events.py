"""Provider-neutral stream events. Every concrete Protocol (OllamaChat,
AnthropicMessages, ...) parses its native chunks into this union, so the
Agent loop never sees provider shapes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LLMEvent:
    """Marker base."""


@dataclass(frozen=True)
class TextDelta(LLMEvent):
    text: str


@dataclass(frozen=True)
class ToolCallStarted(LLMEvent):
    call_id: str
    name: str


@dataclass(frozen=True)
class ToolCallInputDelta(LLMEvent):
    call_id: str
    json_delta: str


@dataclass(frozen=True)
class ToolCallEnded(LLMEvent):
    call_id: str


@dataclass(frozen=True)
class FinishedReason(LLMEvent):
    reason: Literal["stop", "tool_calls", "length", "error"]
