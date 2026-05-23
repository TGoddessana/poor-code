"""Provider-neutral Protocol typing.

Every concrete protocol (OpenAICompatibleChat, AnthropicMessages, ...) implements this
shape. Lives in its own module so `route.py` can depend on the typing without
importing a specific protocol implementation.
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol as _PyProtocol

from poor_code.provider.events import LLMEvent


class Protocol(_PyProtocol):
    def build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]: ...

    def for_stream(self) -> "Protocol": ...

    def parse_chunk(self, chunk: dict[str, Any]) -> Iterable[LLMEvent]: ...
