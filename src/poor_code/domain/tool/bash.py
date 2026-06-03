"""BashTool — execute a shell command in the working directory."""
from __future__ import annotations

import asyncio
import os
import shlex
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult, ToolContext

_OUTPUT_LIMIT = 30_000
_BG_GRACE_SECONDS = 1.2  # window to catch a process that crashes on startup
_BG_LOG_TAIL = 2_000


class BashParams(BaseModel):
    command: str = Field(description="Shell command to execute via /bin/sh -c.")
    timeout: int = Field(
        default=120, ge=1, le=600, description="Max seconds before the command is killed."
    )
    background: bool = Field(
        default=False,
        description=(
            "If true, launch the command as a detached, long-lived process (its own "
            "session, survives this agent exiting) and return immediately with its pid "
            "and early output, instead of waiting. Use for servers/daemons that must "
            "keep running."
        ),
    )


class BashTool:
    id = "bash"
    description = (
        "Execute a shell command in the working directory. "
        "Returns combined stdout+stderr and exit code. "
        "Non-zero exit codes are reported in the output, not raised. "
        "Set background=true to launch a long-lived process (e.g. a server) that keeps "
        "running after this call and after the agent exits; it returns the pid and the "
        "first second of output so you can see startup failures."
    )
    params = BashParams

    async def execute(self, args: BashParams, ctx: ToolContext) -> ExecuteResult:
        if ctx.cancel.is_set():
            raise asyncio.CancelledError
        if args.background:
            return await self._run_background(args, ctx)

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

    async def _run_background(self, args: BashParams, ctx: ToolContext) -> ExecuteResult:
        """Launch detached (its own session) and return immediately with pid + early
        output. Never kills the child — a backgrounded process is meant to outlive this
        call and the agent itself.

        `start_new_session=True` calls os.setsid() in the spawned shell (portable across
        macOS and Linux — unlike the `setsid` binary, which Linux-only), putting the
        launched process in a fresh session detached from poor-code's. The command is
        wrapped in `sh -c '<command>'` so the redirect+background apply to the whole
        command (not just its last clause), and its stdio is redirected to a log file
        OUTSIDE cwd so it neither holds the pipe open nor pollutes the git-diff snapshot.
        """
        fd, log_path = tempfile.mkstemp(prefix="poorcode-bg-", suffix=".log")
        os.close(fd)
        launcher = (
            f"sh -c {shlex.quote(args.command)} "
            f">{shlex.quote(log_path)} 2>&1 </dev/null & echo $!"
        )
        proc = await asyncio.create_subprocess_shell(
            launcher,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ctx.cwd),
            start_new_session=True,
        )
        out_bytes, _ = await proc.communicate()
        pid = out_bytes.decode("utf-8", errors="replace").strip().split("\n")[-1].strip()

        alive = await self._await_liveness(pid)
        log_tail = self._read_tail(log_path)

        state = f"[running pid {pid}]" if alive else "[exited within ~1s]"
        output = f"{state}\n{log_tail}".rstrip()
        title = args.command if len(args.command) <= 80 else args.command[:77] + "..."
        return ExecuteResult(
            title=title,
            output=output,
            metadata={"pid": pid, "background": True, "alive": alive, "log": log_path},
        )

    async def _await_liveness(self, pid: str) -> bool:
        """Poll `kill -0` across the grace window; True only if it stays alive."""
        if not pid.isdigit():
            return False
        elapsed = 0.0
        interval = 0.2
        alive = await self._pid_alive(pid)
        while alive and elapsed < _BG_GRACE_SECONDS:
            await asyncio.sleep(interval)
            elapsed += interval
            alive = await self._pid_alive(pid)
        return alive

    @staticmethod
    async def _pid_alive(pid: str) -> bool:
        proc = await asyncio.create_subprocess_shell(
            f"kill -0 {pid}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0

    @staticmethod
    def _read_tail(log_path: str) -> str:
        try:
            text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-_BG_LOG_TAIL:]
