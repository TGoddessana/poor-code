"""GlobTool — find FILE paths by glob pattern (e.g. '**/*.py'), most-recently
modified first. Read-only; never calls ctx.ask. This is the cheap 'what files
exist' tool, distinct from grep ('what is inside them'); having it stops the
model from abusing grep over '**/*' to enumerate files. Refuses patterns that
escape the working dir."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext, reject_escaping_glob


class GlobParams(BaseModel):
    pattern: str = Field(
        description="Glob pattern relative to the working dir, e.g. '**/*.py' or 'src/*.ts'.")
    max_results: int = Field(default=200, ge=1, le=2000)


class GlobTool:
    id = "glob"
    description = (
        "Find file paths matching a glob pattern (e.g. '**/*.py'), most-recently "
        "modified first. Use this to discover which files exist; use grep to search "
        "their contents.")
    params = GlobParams

    async def execute(self, args: GlobParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError
        reject_escaping_glob(args.pattern)

        root = ctx.cwd.resolve()
        files = [p for p in root.glob(args.pattern) if p.is_file()]
        # Defensive: drop anything that resolved outside root (symlinks, etc.).
        files = [p for p in files if root == p.resolve() or root in p.resolve().parents]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        rels = [str(p.relative_to(root)) for p in files[:args.max_results]]
        return ExecuteResult(
            title=f"glob {args.pattern}",
            output="\n".join(rels) if rels else "(no matches)",
        )
