"""FakeLLMClient — scripted LLMEvent streams for testing Agent.

Use either:
  FakeLLMClient([[ev, ev, ev], [ev, ev]])    # list of rounds
or:
  FakeLLMClient.text_only("hello")           # convenience: one round of text
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Iterable

from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
)


class FakeLLMClient:
    def __init__(self, rounds: list[list[LLMEvent]]) -> None:
        self._rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []  # captured stream() args, for assertions

    @classmethod
    def text_only(cls, text: str) -> "FakeLLMClient":
        return cls([[TextDelta(text=text), FinishedReason(reason="stop")]])

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        if not self._rounds:
            raise AssertionError("FakeLLMClient.stream called more times than scripted")
        events = self._rounds.pop(0)
        for ev in events:
            yield ev
