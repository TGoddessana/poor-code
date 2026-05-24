import asyncio
from pathlib import Path

import pytest

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.write import WriteParams, WriteTool


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(turn_id="T", cancel=asyncio.Event(), cwd=cwd, ask=allow_all)


@pytest.mark.asyncio
async def test_write_new_file(tmp_path):
    tool = WriteTool()
    result = await tool.execute(
        WriteParams(path="hello.txt", content="hello world"), _ctx(tmp_path)
    )
    assert (tmp_path / "hello.txt").read_text() == "hello world"
    assert "Wrote 11 bytes" in result.output


@pytest.mark.asyncio
async def test_write_overwrites_existing(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("old")
    tool = WriteTool()
    await tool.execute(WriteParams(path="x.txt", content="new"), _ctx(tmp_path))
    assert f.read_text() == "new"


@pytest.mark.asyncio
async def test_write_creates_parent_dirs(tmp_path):
    tool = WriteTool()
    await tool.execute(
        WriteParams(path="sub/nested/f.txt", content="deep"), _ctx(tmp_path)
    )
    assert (tmp_path / "sub" / "nested" / "f.txt").read_text() == "deep"


@pytest.mark.asyncio
async def test_write_rejects_path_outside_cwd(tmp_path):
    tool = WriteTool()
    with pytest.raises(PermissionError, match="outside cwd"):
        await tool.execute(WriteParams(path="/etc/passwd", content="x"), _ctx(tmp_path))


@pytest.mark.asyncio
async def test_write_honors_cancel(tmp_path):
    tool = WriteTool()
    ctx = _ctx(tmp_path)
    ctx.cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await tool.execute(WriteParams(path="x.txt", content="x"), ctx)
