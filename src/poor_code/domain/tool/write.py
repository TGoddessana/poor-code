"""WriteTool — write content to a file, overwriting if it exists."""
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext


class WriteParams(BaseModel):
    path: str = Field(description="File path. Relative paths resolve against the working dir.")
    content: str = Field(description="Content to write to the file.")


class WriteTool:
    id = "write"
    description = "Write content to a file, overwriting if it exists. Creates parent directories as needed."
    params = WriteParams

    async def execute(self, args: WriteParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError

        raw = Path(args.path)
        target = (ctx.cwd / raw).resolve() if not raw.is_absolute() else raw.resolve()
        cwd_resolved = ctx.cwd.resolve()
        if cwd_resolved != target and cwd_resolved not in target.parents:
            raise PermissionError(f"path outside cwd: {args.path}")

        target.parent.mkdir(parents=True, exist_ok=True)
        content_bytes = args.content.encode("utf-8")
        target.write_bytes(content_bytes)

        return ExecuteResult(
            title=f"Wrote {args.path}",
            output=f"Wrote {len(content_bytes)} bytes to {args.path}",
        )
