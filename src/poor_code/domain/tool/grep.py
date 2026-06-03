"""GrepTool — search file contents by regular expression. Read-only; never
calls ctx.ask. Returns 'file:lineno: line' matches, bounded by max_results."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import (
    ExecuteResult, ToolContext, reject_escaping_glob,
)


class GrepParams(BaseModel):
    pattern: str = Field(description="Regular expression to search for.")
    path_glob: str | None = Field(
        default=None, description="Optional glob to limit files, e.g. 'src/**/*.py'.")
    max_results: int = Field(default=100, ge=1, le=1000)


class GrepTool:
    id = "grep"
    description = "Search file contents by regex. Returns 'file:lineno: line' matches."
    params = GrepParams

    async def execute(self, args: GrepParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError
        try:
            rx = re.compile(args.pattern)
        except re.error as e:
            raise ValueError(f"invalid regex: {e}")
        if args.path_glob:
            reject_escaping_glob(args.path_glob)

        root = ctx.cwd.resolve()
        results: list[str] = []
        for path in sorted(root.glob(args.path_glob or "**/*")):
            if not path.is_file():
                continue
            # Defensive: never read a file that resolved outside the working dir.
            if root != path.resolve() and root not in path.resolve().parents:
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if rx.search(line):
                            results.append(f"{path.relative_to(root)}:{i}: {line.rstrip()}")
                            if len(results) >= args.max_results:
                                break
            except OSError:
                continue
            if len(results) >= args.max_results:
                break

        return ExecuteResult(
            title=f"grep {args.pattern}",
            output="\n".join(results) if results else "(no matches)",
        )
