import asyncio
import re
import pytest

from poor_code.domain.harness.snapshot import GitSnapshot, default_git_dir


@pytest.mark.asyncio
async def test_baseline_and_diff_since_captures_new_and_edited_files(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "existing.txt").write_text("v1\n")
    gitdir = tmp_path / "shadow"
    snap = GitSnapshot(git_dir=gitdir, work_tree=work)
    await snap.init()

    base = await snap.baseline()
    assert re.fullmatch(r"[0-9a-f]{40}", base)  # write-tree returns a tree sha

    # mutate: new file + edit existing (simulating write/edit/bash)
    (work / "new.txt").write_text("hello\n")
    (work / "existing.txt").write_text("v2\n")

    files, diff = await snap.diff_since(base)
    assert set(files) == {"new.txt", "existing.txt"}
    assert "hello" in diff and "v2" in diff


@pytest.mark.asyncio
async def test_diff_since_empty_when_no_changes(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.txt").write_text("x")
    snap = GitSnapshot(git_dir=tmp_path / "s", work_tree=work)
    await snap.init()
    base = await snap.baseline()
    files, diff = await snap.diff_since(base)
    assert files == ()
    assert diff == ""


@pytest.mark.asyncio
async def test_bash_made_change_is_captured(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    snap = GitSnapshot(git_dir=tmp_path / "s", work_tree=work)
    await snap.init()
    base = await snap.baseline()
    # change made by an external process (not write/edit) — must still be seen
    proc = await asyncio.create_subprocess_shell("echo hi > sneaky.txt", cwd=str(work))
    await proc.wait()
    files, _ = await snap.diff_since(base)
    assert "sneaky.txt" in files


def test_default_git_dir_is_outside_work_tree(tmp_path):
    work = tmp_path / "proj"
    work.mkdir()
    gd = default_git_dir(work)
    assert work.resolve() not in gd.resolve().parents
    assert gd.resolve() != work.resolve()
