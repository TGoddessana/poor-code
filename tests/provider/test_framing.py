import pytest

from poor_code.provider.framing import NdjsonFraming


async def _aiter(items):
    for x in items:
        yield x


@pytest.mark.asyncio
async def test_ndjson_framing_yields_each_line():
    raw = [b'{"a":1}\n', b'{"b":2}\n', b'{"c":3}\n']
    out = [chunk async for chunk in NdjsonFraming().frames(_aiter(raw))]
    assert out == [b'{"a":1}', b'{"b":2}', b'{"c":3}']


@pytest.mark.asyncio
async def test_ndjson_framing_handles_split_across_reads():
    raw = [b'{"a":', b'1}\n{"b":2', b'}\n']
    out = [chunk async for chunk in NdjsonFraming().frames(_aiter(raw))]
    assert out == [b'{"a":1}', b'{"b":2}']


@pytest.mark.asyncio
async def test_ndjson_framing_skips_blank_lines():
    raw = [b'\n{"a":1}\n\n{"b":2}\n\n']
    out = [chunk async for chunk in NdjsonFraming().frames(_aiter(raw))]
    assert out == [b'{"a":1}', b'{"b":2}']


@pytest.mark.asyncio
async def test_ndjson_framing_yields_trailing_unterminated_line():
    """Some servers omit the final newline; we must still yield the last record."""
    raw = [b'{"a":1}\n{"b":2}']
    out = [chunk async for chunk in NdjsonFraming().frames(_aiter(raw))]
    assert out == [b'{"a":1}', b'{"b":2}']
