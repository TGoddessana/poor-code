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
