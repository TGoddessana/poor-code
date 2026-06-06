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
    Pricing/cost is computed by the Agent layer, not here.

    `cached_input_tokens` is the portion of `input_tokens` the provider served
    from a prefix/KV cache (OpenAI: usage.prompt_tokens_details.cached_tokens).
    0 when the provider does not report cache hits. Surfacing it lets the harness
    MEASURE whether prefix caching is actually happening (the open question the
    low-param research flagged for Ollama Cloud) instead of inferring it."""
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
