import asyncio
import pytest
from pathlib import Path
from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.grep import GrepTool, GrepParams


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(turn_id="t", cancel=asyncio.Event(), cwd=cwd, ask=allow_all)


@pytest.mark.asyncio
async def test_grep_finds_matches_with_file_and_lineno(tmp_path):
    (tmp_path / "a.py").write_text("def build_provider():\n    return None\n")
    (tmp_path / "b.py").write_text("x = 1\n")
    res = await GrepTool().execute(GrepParams(pattern="build_provider"), _ctx(tmp_path))
    assert "a.py:1:" in res.output
    assert "build_provider" in res.output
    assert "b.py" not in res.output


@pytest.mark.asyncio
async def test_grep_no_matches_returns_marker(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    res = await GrepTool().execute(GrepParams(pattern="zzz_nope"), _ctx(tmp_path))
    assert res.output == "(no matches)"


@pytest.mark.asyncio
async def test_grep_respects_path_glob(tmp_path):
    (tmp_path / "keep.py").write_text("target\n")
    (tmp_path / "skip.txt").write_text("target\n")
    res = await GrepTool().execute(
        GrepParams(pattern="target", path_glob="*.py"), _ctx(tmp_path))
    assert "keep.py" in res.output
    assert "skip.txt" not in res.output


@pytest.mark.asyncio
async def test_grep_invalid_regex_raises(tmp_path):
    with pytest.raises(ValueError):
        await GrepTool().execute(GrepParams(pattern="("), _ctx(tmp_path))


@pytest.mark.asyncio
async def test_grep_rejects_parent_escaping_glob(tmp_path):
    # A '../**/*' glob walked out of cwd into the container filesystem and OOM'd
    # the process. The tool must refuse to escape cwd.
    (tmp_path / "secret_outside.txt")  # not created; we just must not reach it
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.py").write_text("target\n")
    with pytest.raises(ValueError):
        await GrepTool().execute(
            GrepParams(pattern="target", path_glob="../**/*"), _ctx(work))


@pytest.mark.asyncio
async def test_grep_rejects_absolute_glob(tmp_path):
    with pytest.raises(ValueError):
        await GrepTool().execute(
            GrepParams(pattern="x", path_glob="/etc/**/*"), _ctx(tmp_path))
