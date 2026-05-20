import pytest

from poor_code.provider.framing import SseFraming


async def _aiter(items):
    for x in items:
        yield x


@pytest.mark.asyncio
async def test_sse_framing_splits_data_lines():
    raw = [
        b'data: {"a":1}\n\n',
        b'data: {"b":2}\n\n',
        b"data: [DONE]\n\n",
    ]
    framing = SseFraming()
    out = [chunk async for chunk in framing.frames(_aiter(raw))]
    assert out == [b'{"a":1}', b'{"b":2}']


@pytest.mark.asyncio
async def test_sse_framing_handles_split_across_reads():
    raw = [b'data: {"a":', b'1}\n\n', b"data: [DONE]\n\n"]
    framing = SseFraming()
    out = [chunk async for chunk in framing.frames(_aiter(raw))]
    assert out == [b'{"a":1}']


@pytest.mark.asyncio
async def test_sse_framing_ignores_blank_and_comment_lines():
    raw = [b": ping\n\n", b'data: {"a":1}\n\n', b"data: [DONE]\n\n"]
    framing = SseFraming()
    out = [chunk async for chunk in framing.frames(_aiter(raw))]
    assert out == [b'{"a":1}']
