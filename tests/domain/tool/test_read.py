import asyncio
from pathlib import Path

import pytest

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.read import ReadParams, ReadTool


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(turn_id="T", cancel=asyncio.Event(), cwd=cwd, ask=allow_all)


@pytest.mark.asyncio
async def test_read_small_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line one\nline two\n")
    tool = ReadTool()
    result = await tool.execute(ReadParams(path="hello.txt"), _ctx(tmp_path))
    assert result.title == str(f.resolve())
    assert result.output == "     1\tline one\n     2\tline two\n"


@pytest.mark.asyncio
async def test_read_with_start_and_limit(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("\n".join(f"L{i}" for i in range(1, 6)) + "\n")
    tool = ReadTool()
    result = await tool.execute(ReadParams(path="x.txt", start=2, limit=2), _ctx(tmp_path))
    assert result.output == "     2\tL2\n     3\tL3\n"


@pytest.mark.asyncio
async def test_read_missing_file_raises(tmp_path):
    tool = ReadTool()
    with pytest.raises(FileNotFoundError):
        await tool.execute(ReadParams(path="nope.txt"), _ctx(tmp_path))


@pytest.mark.asyncio
async def test_read_rejects_path_outside_cwd(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("nope")
    try:
        tool = ReadTool()
        with pytest.raises(PermissionError, match="outside cwd"):
            await tool.execute(ReadParams(path=str(outside)), _ctx(tmp_path))
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_read_honors_cancel(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("a\n")
    tool = ReadTool()
    ctx = _ctx(tmp_path)
    ctx.cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await tool.execute(ReadParams(path="x.txt"), ctx)


# --- read dedup against a session ReadCache (Claude Code's readFileState) ---
from poor_code.domain.tool.read import FILE_UNCHANGED_STUB
from poor_code.domain.tool.read_cache import ReadCache


def _ctx_cached(cwd: Path, cache: ReadCache) -> ToolContext:
    return ToolContext(turn_id="T", cancel=asyncio.Event(), cwd=cwd, ask=allow_all,
                       read_cache=cache)


@pytest.mark.asyncio
async def test_read_dedups_unchanged_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line one\nline two\n")
    tool = ReadTool()
    cache = ReadCache()
    first = await tool.execute(ReadParams(path="a.txt"), _ctx_cached(tmp_path, cache))
    assert first.output == "     1\tline one\n     2\tline two\n"
    # identical re-read of the unchanged file → stub, not the body again
    second = await tool.execute(ReadParams(path="a.txt"), _ctx_cached(tmp_path, cache))
    assert second.output == FILE_UNCHANGED_STUB


@pytest.mark.asyncio
async def test_read_rereads_when_file_changed(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("old\n")
    tool = ReadTool()
    cache = ReadCache()
    await tool.execute(ReadParams(path="a.txt"), _ctx_cached(tmp_path, cache))
    # mutate the file → mtime changes → the cache entry is stale → full re-read
    import os, time
    f.write_text("new content\n")
    os.utime(f, ns=(time.time_ns(), time.time_ns() + 1_000_000))  # force a distinct mtime
    again = await tool.execute(ReadParams(path="a.txt"), _ctx_cached(tmp_path, cache))
    assert again.output == "     1\tnew content\n"


@pytest.mark.asyncio
async def test_read_different_range_is_not_a_hit(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("\n".join(f"L{i}" for i in range(1, 6)) + "\n")
    tool = ReadTool()
    cache = ReadCache()
    await tool.execute(ReadParams(path="a.txt", start=1, limit=2), _ctx_cached(tmp_path, cache))
    # a different slice of the same file must read for real, not return the stub
    other = await tool.execute(ReadParams(path="a.txt", start=3, limit=2), _ctx_cached(tmp_path, cache))
    assert other.output == "     3\tL3\n     4\tL4\n"
