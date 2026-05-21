from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from poor_code.infra.context_loader import ContextLoader, LoadedContext


class _FakeGit:
    def __init__(
        self, is_repo: bool = True, status: str = "", branch: str = "main",
        commits: str = "",
    ) -> None:
        self._is_repo = is_repo
        self._status = status
        self._branch = branch
        self._commits = commits

    async def is_repo(self, cwd: Path) -> bool:
        return self._is_repo

    async def status(self, cwd: Path) -> str:
        return self._status

    async def branch(self, cwd: Path) -> str:
        return self._branch

    async def recent_commits(self, cwd: Path, n: int) -> str:
        return self._commits


def _fixed_now() -> dt.datetime:
    return dt.datetime(2026, 5, 21, 12, 0, 0)


async def test_no_poorcode_files_user_block_only_contains_date(tmp_path):
    loader = ContextLoader(
        home_dir=tmp_path / "home", git=_FakeGit(is_repo=False), now=_fixed_now
    )
    result = await loader.load(cwd=tmp_path / "project")
    assert isinstance(result, LoadedContext)
    assert "2026-05-21" in result.user_block
    assert result.sources == ()


async def test_global_only(tmp_path):
    home = tmp_path / "home"
    (home / ".poor-code").mkdir(parents=True)
    (home / ".poor-code" / "POORCODE.md").write_text("GLOBAL CONTENT")
    project = tmp_path / "project"
    project.mkdir()

    loader = ContextLoader(home_dir=home, git=_FakeGit(is_repo=False), now=_fixed_now)
    result = await loader.load(cwd=project)

    assert "GLOBAL CONTENT" in result.user_block
    assert result.sources == (home / ".poor-code" / "POORCODE.md",)


async def test_global_then_project_order(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".poor-code").mkdir(parents=True)
    (home / ".poor-code" / "POORCODE.md").write_text("GLOBAL CONTENT")
    project.mkdir()
    (project / "POORCODE.md").write_text("PROJECT CONTENT")

    loader = ContextLoader(home_dir=home, git=_FakeGit(is_repo=False), now=_fixed_now)
    result = await loader.load(cwd=project)

    assert result.user_block.index("GLOBAL") < result.user_block.index("PROJECT")
    assert len(result.sources) == 2


async def test_not_a_repo_system_block(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    loader = ContextLoader(
        home_dir=tmp_path / "home", git=_FakeGit(is_repo=False), now=_fixed_now
    )
    result = await loader.load(cwd=project)
    assert "Not a git repository" in result.system_block


async def test_repo_system_block_contains_branch_status_commits(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    loader = ContextLoader(
        home_dir=tmp_path / "home",
        git=_FakeGit(
            is_repo=True, status="?? new.txt\n", branch="feat/x",
            commits="abc123 init\n",
        ),
        now=_fixed_now,
    )
    result = await loader.load(cwd=project)
    assert "feat/x" in result.system_block
    assert "?? new.txt" in result.system_block
    assert "abc123 init" in result.system_block


async def test_empty_poorcode_file_skipped(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".poor-code").mkdir(parents=True)
    (home / ".poor-code" / "POORCODE.md").write_text("   \n\n")
    project.mkdir()

    loader = ContextLoader(home_dir=home, git=_FakeGit(is_repo=False), now=_fixed_now)
    result = await loader.load(cwd=project)
    assert result.sources == ()  # empty file not counted
