"""BashTool — execute a shell command in the working directory."""
from __future__ import annotations

import asyncio
import os
import shlex
import signal
import tempfile
from contextlib import suppress
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

        # start_new_session=True puts the command in its OWN process group, so on timeout
        # or cancel we can SIGKILL the whole group (os.killpg) — not just the direct child.
        # That is the crux: a server (python3 app.py / nginx) keeps the stdout pipe open and
        # forks workers that inherit it; killing only the shell leaves the pipe open, so a
        # read/communicate never reaches EOF and the timeout effectively never fires (the old
        # wait_for(communicate()) only returned when the process exited on its own — never,
        # for a server — freezing the agent until the outer harness timeout).
        proc = await asyncio.create_subprocess_shell(
            args.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ctx.cwd),
            start_new_session=True,
        )

        # Read the combined output in its own task. We wait on (read OR cancel) with a
        # timeout; we never rely on CANCELLING the read (that is what hung). On timeout/cancel
        # we kill the group FIRST, which closes the pipe, so the read then completes promptly
        # with whatever was buffered.
        read_task = asyncio.create_task(proc.stdout.read())
        cancel_task = asyncio.create_task(ctx.cancel.wait())
        timed_out = False
        try:
            done, _ = await asyncio.wait(
                {read_task, cancel_task}, timeout=args.timeout,
                return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done:
                self._killpg(proc)
                with suppress(BaseException):
                    await read_task
                with suppress(Exception):
                    await proc.wait()
                raise asyncio.CancelledError
            if read_task not in done:          # neither finished in time → timeout
                timed_out = True
                self._killpg(proc)             # closes the pipe so the read can finish
            stdout_bytes = await read_task
        finally:
            cancel_task.cancel()
            with suppress(asyncio.CancelledError):
                await cancel_task

        await proc.wait()
        exit_code = 124 if timed_out else proc.returncode

        output = stdout_bytes.decode("utf-8", errors="replace")
        truncated = len(output) > _OUTPUT_LIMIT
        if truncated:
            output = output[:_OUTPUT_LIMIT]

        suffix_parts = []
        if truncated:
            suffix_parts.append(f"[output truncated to {_OUTPUT_LIMIT} chars]")
        if timed_out:
            suffix_parts.append(
                f"[command timed out after {args.timeout}s — killed. If this is a server or "
                f"other long-lived process, relaunch it with background=true.]")
        suffix_parts.append(f"[exit {exit_code}]")
        suffix = "\n\n" + "\n".join(suffix_parts)

        title = args.command if len(args.command) <= 80 else args.command[:77] + "..."
        return ExecuteResult(
            title=title,
            output=output + suffix,
            metadata={"exit_code": exit_code},
        )

    @staticmethod
    def _killpg(proc: asyncio.subprocess.Process) -> None:
        """SIGKILL the command's whole process group (it was started with its own session),
        so a server plus any workers/grandchildren that inherited the pipe all die. Falls
        back to killing just the child if the group is already gone."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            with suppress(ProcessLookupError):
                proc.kill()

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
