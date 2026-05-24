import asyncio
from pathlib import Path

import pytest

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.edit import EditParams, EditTool


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(turn_id="T", cancel=asyncio.Event(), cwd=cwd, ask=allow_all)


@pytest.mark.asyncio
async def test_edit_replaces_single_occurrence(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello world")
    tool = EditTool()
    result = await tool.execute(
        EditParams(path="x.txt", old_string="hello", new_string="hi"), _ctx(tmp_path)
    )
    assert f.read_text() == "hi world"
    assert "Replaced 1 occurrence" in result.output


@pytest.mark.asyncio
async def test_edit_not_found_raises(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello world")
    tool = EditTool()
    with pytest.raises(ValueError, match="not found"):
        await tool.execute(
            EditParams(path="x.txt", old_string="nope", new_string="x"), _ctx(tmp_path)
        )


@pytest.mark.asyncio
async def test_edit_non_unique_raises(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello hello")
    tool = EditTool()
    with pytest.raises(ValueError, match="not unique"):
        await tool.execute(
            EditParams(path="x.txt", old_string="hello", new_string="x"), _ctx(tmp_path)
        )


@pytest.mark.asyncio
async def test_edit_missing_file_raises(tmp_path):
    tool = EditTool()
    with pytest.raises(FileNotFoundError):
        await tool.execute(
            EditParams(path="nope.txt", old_string="a", new_string="b"), _ctx(tmp_path)
        )


@pytest.mark.asyncio
async def test_edit_rejects_path_outside_cwd(tmp_path):
    tool = EditTool()
    with pytest.raises(PermissionError, match="outside cwd"):
        await tool.execute(
            EditParams(path="/etc/passwd", old_string="a", new_string="b"), _ctx(tmp_path)
        )


@pytest.mark.asyncio
async def test_edit_honors_cancel(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("a")
    tool = EditTool()
    ctx = _ctx(tmp_path)
    ctx.cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await tool.execute(EditParams(path="x.txt", old_string="a", new_string="b"), ctx)
