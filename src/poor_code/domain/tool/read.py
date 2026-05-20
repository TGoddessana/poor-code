"""ReadTool — read a single text file with line numbers (cat -n format).

Read-only; never calls ctx.ask (always safe). Refuses paths outside ctx.cwd.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext


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

        raw = Path(args.path)
        target = (ctx.cwd / raw).resolve() if not raw.is_absolute() else raw.resolve()
        cwd_resolved = ctx.cwd.resolve()
        if cwd_resolved != target and cwd_resolved not in target.parents:
            raise PermissionError(f"path outside cwd: {args.path}")

        if not target.is_file():
            raise FileNotFoundError(args.path)

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

        return ExecuteResult(title=str(target), output="".join(lines))
