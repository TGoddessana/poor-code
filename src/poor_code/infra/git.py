"""Git subprocess abstraction.

The default implementation, SubprocessGit, calls `git` via asyncio subprocess
with a 5s per-command timeout. Tests substitute a FakeGit at the _GitLike
Protocol boundary. ContextLoader holds a _GitLike and is unaware of subprocess.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable


GIT_TIMEOUT_SECONDS = 5.0


@runtime_checkable
class _GitLike(Protocol):
    async def is_repo(self, cwd: Path) -> bool: ...
    async def status(self, cwd: Path) -> str: ...
    async def branch(self, cwd: Path) -> str: ...
    async def recent_commits(self, cwd: Path, n: int) -> str: ...


class SubprocessGit:
    async def is_repo(self, cwd: Path) -> bool:
        ok, _ = await _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd)
        return ok

    async def status(self, cwd: Path) -> str:
        _, out = await _run(["git", "status", "--porcelain=v1"], cwd=cwd)
        return out

    async def branch(self, cwd: Path) -> str:
        _, out = await _run(["git", "branch", "--show-current"], cwd=cwd)
        return out.strip()

    async def recent_commits(self, cwd: Path, n: int) -> str:
        _, out = await _run(
            ["git", "log", f"-{n}", "--oneline", "--no-decorate"], cwd=cwd
        )
        return out


async def _run(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError):
        return False, ""

    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(), timeout=GIT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, ""
    except BaseException:
        proc.kill()
        await proc.wait()
        raise

    return proc.returncode == 0, stdout.decode("utf-8", errors="replace")
