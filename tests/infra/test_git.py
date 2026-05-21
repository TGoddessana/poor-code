from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from poor_code.infra.git import SubprocessGit


def _git_init(path: Path) -> None:
    """Create an isolated git repo with one commit so we have a stable HEAD."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    (path / "seed.txt").write_text("seed")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=path, check=True)


async def test_is_repo_false_for_plain_dir(tmp_path):
    git = SubprocessGit()
    assert await git.is_repo(tmp_path) is False


async def test_is_repo_true_after_init(tmp_path):
    _git_init(tmp_path)
    git = SubprocessGit()
    assert await git.is_repo(tmp_path) is True


async def test_status_clean_repo(tmp_path):
    _git_init(tmp_path)
    git = SubprocessGit()
    result = await git.status(tmp_path)
    assert result == ""  # clean working tree


async def test_status_with_untracked(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "new.txt").write_text("x")
    git = SubprocessGit()
    result = await git.status(tmp_path)
    assert "?? new.txt" in result


async def test_branch_returns_current(tmp_path):
    _git_init(tmp_path)
    git = SubprocessGit()
    result = await git.branch(tmp_path)
    assert result == "main"


async def test_recent_commits_includes_seed(tmp_path):
    _git_init(tmp_path)
    git = SubprocessGit()
    result = await git.recent_commits(tmp_path, 5)
    assert "seed" in result


async def test_no_git_installed_returns_empty(tmp_path, monkeypatch):
    # Simulate "git not installed" by emptying PATH.
    monkeypatch.setenv("PATH", "")
    git = SubprocessGit()
    assert await git.is_repo(tmp_path) is False
    assert await git.status(tmp_path) == ""
