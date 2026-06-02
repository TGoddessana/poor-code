"""Shadow-git snapshot — opencode's mechanism ported (snapshot/index.ts).

We never touch the user's/project's .git. We run every git command with an
explicit `--git-dir` (a private object store we own) and `--work-tree` (the real
project dir). A snapshot is a `git write-tree` tree hash (cheap, no commit, no
refs). `git diff --cached <tree>` shows everything changed since that tree —
including changes made by bash, so eng_gate's scope check can't be fooled.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

# env vars that, if inherited from a parent git context, would override our
# explicit --git-dir/--work-tree and corrupt the wrong repo (opencode #22477).
_STRIP_ENV = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY")


def default_git_dir(work_tree: Path) -> Path:
    """A stable shadow git dir OUTSIDE the work-tree (so `git add -A` never
    stages it). Keyed by the work-tree path so attempts in one run share it."""
    key = hashlib.sha1(str(work_tree.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "poor_code_snapshots" / key


class GitSnapshot:
    def __init__(self, git_dir: Path, work_tree: Path) -> None:
        self._git_dir = git_dir
        self._work_tree = work_tree

    async def init(self) -> None:
        if (self._git_dir / "HEAD").exists():
            return  # idempotent
        self._git_dir.mkdir(parents=True, exist_ok=True)
        await self._git("init")
        await self._git("config", "core.autocrlf", "false")
        await self._git("config", "core.longpaths", "true")

    async def baseline(self) -> str:
        """Stage the current work-tree and snapshot it as a tree hash."""
        await self._git("add", "-A")
        code, out = await self._git("write-tree")
        tree = out.strip()
        if code != 0 or len(tree) != 40:
            raise RuntimeError(f"git write-tree failed (code={code}): {out!r}")
        return tree

    async def diff_since(self, base: str) -> tuple[tuple[str, ...], str]:
        """Return (changed files, unified diff) of the current work-tree vs `base`."""
        await self._git("add", "-A")
        _, names = await self._git("diff", "--cached", "--name-only", base)
        _, diff = await self._git("diff", "--cached", base)
        files = tuple(line for line in names.splitlines() if line.strip())
        return files, diff

    async def _git(self, *args: str) -> tuple[int, str]:
        env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
        proc = await asyncio.create_subprocess_exec(
            "git", "--git-dir", str(self._git_dir), "--work-tree", str(self._work_tree),
            *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            cwd=str(self._work_tree), env=env,
        )
        out_bytes, _ = await proc.communicate()
        return proc.returncode, out_bytes.decode("utf-8", errors="replace")
