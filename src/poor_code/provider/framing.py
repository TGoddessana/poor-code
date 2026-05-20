"""Server-Sent Events framing.

Consumes raw byte chunks from an httpx stream and yields each `data:` payload
as bytes. Terminates on `data: [DONE]`. Ignores blank lines and `:` comments
per the SSE spec.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol


class Framing(Protocol):
    async def frames(self, byte_stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]: ...


class SseFraming:
    async def frames(
        self, byte_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[bytes]:
        buf = b""
        async for chunk in byte_stream:
            buf += chunk
            while b"\n\n" in buf:
                event, buf = buf.split(b"\n\n", 1)
                payload = self._extract_data(event)
                if payload is None:
                    continue
                if payload == b"[DONE]":
                    return
                yield payload

    @staticmethod
    def _extract_data(event: bytes) -> bytes | None:
        # An SSE event can have multiple lines; we only care about `data: ...`.
        data_parts: list[bytes] = []
        for line in event.split(b"\n"):
            if not line or line.startswith(b":"):
                continue
            if line.startswith(b"data:"):
                data_parts.append(line[5:].lstrip())
        if not data_parts:
            return None
        return b"\n".join(data_parts)
