"""EditTool — replace an exact string match in a file."""
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext


class EditParams(BaseModel):
    path: str = Field(description="File path. Relative paths resolve against the working dir.")
    old_string: str = Field(description="The exact string to find and replace.")
    new_string: str = Field(description="The string to replace it with (must be different).")


class EditTool:
    id = "edit"
    description = "Replace an exact string match in a file. Fails if old_string is not unique or not found."
    params = EditParams

    async def execute(self, args: EditParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError

        raw = Path(args.path)
        target = (ctx.cwd / raw).resolve() if not raw.is_absolute() else raw.resolve()
        cwd_resolved = ctx.cwd.resolve()
        if cwd_resolved != target and cwd_resolved not in target.parents:
            raise PermissionError(f"path outside cwd: {args.path}")

        if not target.is_file():
            raise FileNotFoundError(args.path)

        original = target.read_text("utf-8")
        count = original.count(args.old_string)
        if count == 0:
            raise ValueError(f"old_string not found in {args.path}")
        if count > 1:
            raise ValueError(f"old_string is not unique in {args.path} ({count} occurrences)")

        replaced = original.replace(args.old_string, args.new_string, 1)
        target.write_text(replaced, "utf-8")

        return ExecuteResult(
            title=f"Edited {args.path}",
            output=f"Replaced 1 occurrence in {args.path}",
        )
