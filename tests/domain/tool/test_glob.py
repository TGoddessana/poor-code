import asyncio
from pathlib import Path

import pytest

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.glob import GlobParams, GlobTool


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(turn_id="t", cancel=asyncio.Event(), cwd=cwd, ask=allow_all)


@pytest.mark.asyncio
async def test_finds_files_by_pattern(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y\n")
    (tmp_path / "c.txt").write_text("z\n")
    res = await GlobTool().execute(GlobParams(pattern="**/*.py"), _ctx(tmp_path))
    assert "a.py" in res.output
    assert "sub/b.py" in res.output
    assert "c.txt" not in res.output


@pytest.mark.asyncio
async def test_no_match_returns_marker(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    res = await GlobTool().execute(GlobParams(pattern="**/*.rs"), _ctx(tmp_path))
    assert res.output == "(no matches)"


@pytest.mark.asyncio
async def test_lists_only_files_not_directories(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y\n")
    res = await GlobTool().execute(GlobParams(pattern="**/*"), _ctx(tmp_path))
    assert "sub/b.py" in res.output
    # the directory itself is not a result line
    assert not any(line == "sub" for line in res.output.splitlines())


@pytest.mark.asyncio
async def test_rejects_parent_escaping_pattern(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ValueError):
        await GlobTool().execute(GlobParams(pattern="../**/*"), _ctx(work))


@pytest.mark.asyncio
async def test_rejects_absolute_pattern(tmp_path):
    with pytest.raises(ValueError):
        await GlobTool().execute(GlobParams(pattern="/etc/**/*"), _ctx(tmp_path))
