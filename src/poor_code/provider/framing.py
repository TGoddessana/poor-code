"""Newline-delimited JSON framing.

Consumes raw byte chunks from an httpx stream and yields one JSON record per
newline. Blank lines are skipped. A trailing record without a final newline
is still yielded when the stream ends — some servers omit it.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol


class Framing(Protocol):
    async def frames(self, byte_stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]: ...


class NdjsonFraming:
    async def frames(
        self, byte_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[bytes]:
        buf = b""
        async for chunk in byte_stream:
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    yield line
        tail = buf.strip()
        if tail:
            yield tail
