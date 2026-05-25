"""Provider-neutral stream events. Every concrete Protocol (OpenAICompatibleChat,
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


@dataclass(frozen=True)
class UsageEnded(LLMEvent):
    """Provider's reported token counts for the completed stream.
    Pricing/cost is computed by the Agent layer, not here."""
    input_tokens: int
    output_tokens: int
