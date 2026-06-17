"""ReadTool — read a single text file with line numbers (cat -n format).

Read-only; never calls ctx.ask (always safe). Refuses paths outside ctx.cwd.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext
from poor_code.domain.tool.read_cache import FileState, ReadCache

FILE_UNCHANGED_STUB = (
    "File unchanged since your last read — the earlier Read result for this file is "
    "still current in this conversation; refer to it instead of re-reading."
)


class ReadParams(BaseModel):
    path: str = Field(description="File path. Relative paths resolve against the working dir.")
    start: int = Field(default=1, ge=1, description="1-indexed start line.")
    limit: int = Field(default=2000, ge=1, le=10000, description="Max lines to read.")


class ReadTool:
    id = "read"
    description = "Read a single text file with line numbers (cat -n format)."
    params = ReadParams

    async def execute(self, args: ReadParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError
        # Run the blocking file I/O off the event loop so it never freezes the TUI
        # (the harness drives nodes on Textual's loop; synchronous reads would stall it).
        return await asyncio.to_thread(self._read, args, ctx.cwd, ctx.read_cache)

    def _read(self, args: ReadParams, cwd: Path,
              cache: ReadCache | None) -> ExecuteResult:
        raw = Path(args.path)
        target = (cwd / raw).resolve() if not raw.is_absolute() else raw.resolve()
        cwd_resolved = cwd.resolve()
        if cwd_resolved != target and cwd_resolved not in target.parents:
            raise PermissionError(f"path outside cwd: {args.path}")

        if not target.is_file():
            raise FileNotFoundError(args.path)

        # Dedup (Claude Code's readFileState): if this exact range of an UNCHANGED file
        # was already read this session, return a stub instead of the body. mtime is the
        # staleness key, so an Edit/Write between reads bumps it and we re-read.
        key = str(target)
        mtime_ns = target.stat().st_mtime_ns
        if cache is not None and cache.is_fresh_hit(
                key, mtime_ns=mtime_ns, start=args.start, limit=args.limit):
            return ExecuteResult(title=str(target), output=FILE_UNCHANGED_STUB)

        with target.open("r", encoding="utf-8", errors="replace") as fh:
            lines: list[str] = []
            for i, line in enumerate(fh, start=1):
                if i < args.start:
                    continue
                if i >= args.start + args.limit:
                    break
                lines.append(f"{i:>6}\t{line}")
                if not line.endswith("\n"):
                    lines[-1] += "\n"

        output = "".join(lines)
        if cache is not None:
            cache.set(key, FileState(content=output, mtime_ns=mtime_ns,
                                     start=args.start, limit=args.limit))
        return ExecuteResult(title=str(target), output=output)
