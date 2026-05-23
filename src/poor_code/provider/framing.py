"""Server-Sent Events (SSE) framing.

Consumes raw byte chunks from an HTTP stream and yields one JSON payload per
SSE event line (strips the `data: ` prefix). The `[DONE]` sentinel and blank
lines are skipped.
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
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.rstrip(b"\r")
                if line.startswith(b"data: "):
                    payload = line[6:]
                    if payload != b"[DONE]":
                        yield payload
        tail = buf.rstrip(b"\r")
        if tail.startswith(b"data: "):
            payload = tail[6:]
            if payload != b"[DONE]":
                yield payload
