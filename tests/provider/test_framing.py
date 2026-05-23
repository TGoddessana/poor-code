"""SseFraming: extracts JSON payloads from an SSE byte stream."""
from __future__ import annotations

import json
import pytest
from poor_code.provider.framing import SseFraming


async def _collect(chunks: list[bytes]) -> list[bytes]:
    async def _gen():
        for c in chunks:
            yield c
    return [frame async for frame in SseFraming().frames(_gen())]


@pytest.mark.asyncio
async def test_strips_data_prefix():
    payload = json.dumps({"choices": [{"delta": {"content": "hi"}}]}).encode()
    result = await _collect([b"data: " + payload + b"\n\n"])
    assert result == [payload]


@pytest.mark.asyncio
async def test_skips_done_sentinel():
    payload = json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode()
    result = await _collect([
        b"data: " + payload + b"\n\n",
        b"data: [DONE]\n\n",
    ])
    assert result == [payload]


@pytest.mark.asyncio
async def test_skips_empty_lines():
    payload = json.dumps({"choices": [{"delta": {"content": "x"}}]}).encode()
    result = await _collect([b"\n", b"data: " + payload + b"\n", b"\n"])
    assert result == [payload]


@pytest.mark.asyncio
async def test_skips_comment_lines():
    payload = json.dumps({"choices": [{"delta": {"content": "x"}}]}).encode()
    result = await _collect([b": ping\n", b"data: " + payload + b"\n\n"])
    assert result == [payload]


@pytest.mark.asyncio
async def test_handles_chunked_delivery():
    """A single SSE line split across multiple HTTP chunks."""
    payload = json.dumps({"choices": [{"delta": {"content": "hi"}}]}).encode()
    full_line = b"data: " + payload + b"\n\n"
    mid = len(full_line) // 2
    result = await _collect([full_line[:mid], full_line[mid:]])
    assert result == [payload]


@pytest.mark.asyncio
async def test_multiple_events_in_one_chunk():
    p1 = json.dumps({"choices": [{"delta": {"content": "a"}}]}).encode()
    p2 = json.dumps({"choices": [{"delta": {"content": "b"}}]}).encode()
    combined = b"data: " + p1 + b"\n\ndata: " + p2 + b"\n\n"
    result = await _collect([combined])
    assert result == [p1, p2]
