import asyncio
from pathlib import Path

import pytest

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.list import ListParams, ListTool


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(turn_id="t", cancel=asyncio.Event(), cwd=cwd, ask=allow_all)


@pytest.mark.asyncio
async def test_lists_entries_marking_directories(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    (tmp_path / "b.txt").write_text("y\n")
    (tmp_path / "sub").mkdir()
    res = await ListTool().execute(ListParams(path="."), _ctx(tmp_path))
    assert "a.py" in res.output
    assert "b.txt" in res.output
    assert "sub/" in res.output          # directories marked with trailing slash


@pytest.mark.asyncio
async def test_empty_directory_signals_empty(tmp_path):
    # The greenfield case: an empty cwd must be observable in one call so the
    # explorer concludes GREENFIELD instead of grepping forever.
    res = await ListTool().execute(ListParams(path="."), _ctx(tmp_path))
    assert "empty" in res.output.lower()


@pytest.mark.asyncio
async def test_rejects_path_outside_cwd(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(PermissionError):
        await ListTool().execute(ListParams(path=".."), _ctx(work))


@pytest.mark.asyncio
async def test_errors_on_non_directory(tmp_path):
    (tmp_path / "f.txt").write_text("x\n")
    with pytest.raises(NotADirectoryError):
        await ListTool().execute(ListParams(path="f.txt"), _ctx(tmp_path))
