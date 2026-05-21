"""ContextLoader — assembles the per-turn user/system context blocks.

user_block contains POORCODE.md (global + project, concatenated global-first) plus
the current date. system_block contains git status / branch / recent commits, or a
"Not a git repository" note when applicable. Both blocks are strings ready to be
prepended to the first user message.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from poor_code.infra.git import SubprocessGit, _GitLike


@dataclass(frozen=True)
class LoadedContext:
    user_block: str
    system_block: str
    sources: tuple[Path, ...]


class ContextLoader:
    def __init__(
        self,
        home_dir: Path | None = None,
        git: _GitLike | None = None,
        now: Callable[[], _dt.datetime] | None = None,
    ) -> None:
        self._home = home_dir if home_dir is not None else Path.home()
        self._git = git if git is not None else SubprocessGit()
        self._now = now if now is not None else _dt.datetime.now

    async def load(self, cwd: Path) -> LoadedContext:
        sources: list[Path] = []
        chunks: list[str] = []

        for path in (
            self._home / ".poor-code" / "POORCODE.md",
            cwd / "POORCODE.md",
        ):
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                continue
            sources.append(path)
            chunks.append(f'<context source="{path}">\n{text}\n</context>\n')

        date_str = self._now().strftime("%Y-%m-%d")
        chunks.append(f"<context>Today's date: {date_str}</context>\n")
        user_block = "".join(chunks)

        system_block = await self._build_system_block(cwd)

        return LoadedContext(
            user_block=user_block,
            system_block=system_block,
            sources=tuple(sources),
        )

    async def _build_system_block(self, cwd: Path) -> str:
        if not await self._git.is_repo(cwd):
            return "<system>Not a git repository.</system>\n"

        branch = await self._git.branch(cwd)
        status = await self._git.status(cwd)
        commits = await self._git.recent_commits(cwd, 5)

        return (
            "<system>\n"
            f"Current branch: {branch or '(detached)'}\n\n"
            f"Status:\n{status or '(clean)'}\n\n"
            f"Recent commits:\n{commits or '(none)'}\n"
            "</system>\n"
        )
