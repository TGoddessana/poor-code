"""ListTool — list a single directory's entries (one level). Read-only; never
calls ctx.ask. Directories are marked with a trailing '/'. An empty directory
returns an explicit '(empty directory)' marker so the explorer can recognise a
greenfield repo in one call instead of grepping endlessly. Refuses paths
outside ctx.cwd."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext, resolve_within_cwd


class ListParams(BaseModel):
    path: str = Field(
        default=".",
        description="Directory to list (relative to the working dir). Defaults to '.'.")


class ListTool:
    id = "list"
    description = (
        "List a directory's entries (one level). Directories end with '/'. "
        "Use this to see what files exist before reading or grepping — an empty "
        "result means the directory is empty.")
    params = ListParams

    async def execute(self, args: ListParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError

        target = resolve_within_cwd(ctx.cwd, args.path)
        if not target.is_dir():
            raise NotADirectoryError(args.path)

        entries = sorted(
            target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = [f"{p.name}/" if p.is_dir() else p.name for p in entries]
        return ExecuteResult(
            title=f"list {args.path}",
            output="\n".join(lines) if lines else "(empty directory)",
        )
