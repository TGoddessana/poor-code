"""BashTool — execute a shell command in the working directory."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext

_OUTPUT_LIMIT = 30_000


class BashParams(BaseModel):
    command: str = Field(description="Shell command to execute via /bin/sh -c.")
    timeout: int = Field(
        default=120, ge=1, le=600, description="Max seconds before the command is killed."
    )


class BashTool:
    id = "bash"
    description = (
        "Execute a shell command in the working directory. "
        "Returns combined stdout+stderr and exit code. "
        "Non-zero exit codes are reported in the output, not raised."
    )
    params = BashParams

    async def execute(self, args: BashParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError

        proc = await asyncio.create_subprocess_shell(
            args.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ctx.cwd),
        )

        async def _wait_cancel() -> None:
            await ctx.cancel.wait()
            try:
                proc.kill()
            except ProcessLookupError:
                pass

        cancel_task = asyncio.create_task(_wait_cancel())
        try:
            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=args.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"command timed out after {args.timeout}s")
        finally:
            cancel_task.cancel()

        if ctx.cancel.is_set():
            raise asyncio.CancelledError

        output = stdout_bytes.decode("utf-8", errors="replace")
        truncated = len(output) > _OUTPUT_LIMIT
        if truncated:
            output = output[:_OUTPUT_LIMIT]

        suffix_parts = []
        if truncated:
            suffix_parts.append(f"[output truncated to {_OUTPUT_LIMIT} chars]")
        suffix_parts.append(f"[exit {proc.returncode}]")
        suffix = "\n\n" + "\n".join(suffix_parts)

        title = args.command if len(args.command) <= 80 else args.command[:77] + "..."
        return ExecuteResult(
            title=title,
            output=output + suffix,
            metadata={"exit_code": proc.returncode},
        )
