"""Token instrumentation — the harness's single accounting of LLM token spend.

`LLMClient` (the one place every LLM call funnels through) owns a `TokenMeter`
and records each completed stream's `UsageEnded` into it. Totals answer "what did
this run cost"; per-node attribution answers "where did the context bloat / cache
hits land" — the measurement the low-param research needed but lacked (results.json
token counts were all 0). Pure data; no provider coupling beyond the UsageEnded event.
"""
from __future__ import annotations

from dataclasses import dataclass

from poor_code.provider.events import UsageEnded


def tag(llm: object, label: str) -> None:
    """Attribute the next stream's tokens to `label` (the node name). A no-op on
    clients that don't carry a meter (the test fakes), so nodes can call it
    unconditionally without coupling to the concrete LLMClient type."""
    if hasattr(llm, "active_label"):
        llm.active_label = label  # type: ignore[attr-defined]


@dataclass(frozen=True)
class TokenUsage:
    """An immutable token tally. `calls` lets us report averages per call and
    distinguish 'one big call' from 'many small calls' at the same total."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    calls: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            calls=self.calls + other.calls,
        )

    @classmethod
    def from_event(cls, ev: UsageEnded) -> "TokenUsage":
        return cls(
            input_tokens=ev.input_tokens,
            output_tokens=ev.output_tokens,
            cached_input_tokens=ev.cached_input_tokens,
            calls=1,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "calls": self.calls,
        }


class TokenMeter:
    """Mutable running tally. One per LLMClient (so per run, since the client is
    built once). `record` is called from the client's stream chokepoint for every
    UsageEnded; an optional `label` (the node name) adds a per-node breakdown."""

    def __init__(self) -> None:
        self.total = TokenUsage()
        self.by_node: dict[str, TokenUsage] = {}

    def record(self, ev: UsageEnded, *, label: str | None = None) -> None:
        usage = TokenUsage.from_event(ev)
        self.total = self.total + usage
        if label is not None:
            self.by_node[label] = self.by_node.get(label, TokenUsage()) + usage

    def snapshot(self) -> dict[str, object]:
        """A JSON-serializable point-in-time view (for results.json / the footer)."""
        return {
            "total": self.total.as_dict(),
            "by_node": {name: u.as_dict() for name, u in self.by_node.items()},
        }
