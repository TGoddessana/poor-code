import asyncio
import os
import signal
from pathlib import Path

import pytest

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.bash import BashParams, BashTool


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(turn_id="T", cancel=asyncio.Event(), cwd=cwd, ask=allow_all)


@pytest.mark.asyncio
async def test_bash_stdout(tmp_path):
    tool = BashTool()
    result = await tool.execute(BashParams(command="echo hello"), _ctx(tmp_path))
    assert "hello" in result.output
    assert "[exit 0]" in result.output
    assert result.metadata["exit_code"] == 0


@pytest.mark.asyncio
async def test_bash_merges_stderr_into_stdout(tmp_path):
    tool = BashTool()
    result = await tool.execute(
        BashParams(command="echo out; echo err 1>&2"), _ctx(tmp_path)
    )
    assert "out" in result.output
    assert "err" in result.output


@pytest.mark.asyncio
async def test_bash_nonzero_exit_does_not_raise(tmp_path):
    tool = BashTool()
    result = await tool.execute(BashParams(command="false"), _ctx(tmp_path))
    assert result.metadata["exit_code"] == 1
    assert "[exit 1]" in result.output


@pytest.mark.asyncio
async def test_bash_runs_in_ctx_cwd(tmp_path):
    tool = BashTool()
    result = await tool.execute(BashParams(command="pwd"), _ctx(tmp_path))
    assert str(tmp_path.resolve()) in result.output


@pytest.mark.asyncio
async def test_bash_timeout_returns_124_promptly(tmp_path):
    # A single foreground long-running process must be KILLED at the timeout and the call
    # must return PROMPTLY with exit 124 — not block until the process exits on its own.
    # (The old wait_for(communicate()) only "timed out" when the process died naturally, so
    # a server that never exits froze the agent forever.)
    tool = BashTool()
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    result = await asyncio.wait_for(
        tool.execute(BashParams(command="python3 -c 'import time; time.sleep(30)'", timeout=1),
                     _ctx(tmp_path)),
        timeout=10)  # outer guard: a hang fails the test instead of freezing the suite
    assert loop.time() - t0 < 6  # returned promptly (~1s), not after the 30s sleep
    assert result.metadata["exit_code"] == 124
    assert "timed out" in result.output


@pytest.mark.asyncio
async def test_bash_timeout_kills_child_holding_pipe(tmp_path):
    # The server case: a child process inherits the stdout pipe and outlives the parent
    # (like nginx workers / a forked server). Killing only the direct child leaves the pipe
    # open and the read never reaches EOF — so the whole process GROUP must be killed.
    tool = BashTool()
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    result = await asyncio.wait_for(
        tool.execute(BashParams(command="sleep 30 & wait", timeout=1), _ctx(tmp_path)),
        timeout=10)
    assert loop.time() - t0 < 6
    assert result.metadata["exit_code"] == 124


@pytest.mark.asyncio
async def test_bash_timeout_preserves_partial_output(tmp_path):
    # Output printed before the timeout must survive (the agent needs the startup logs to
    # see WHY it hung), alongside the 124 timeout marker.
    tool = BashTool()
    result = await asyncio.wait_for(
        tool.execute(BashParams(command="echo starting; sleep 30", timeout=1), _ctx(tmp_path)),
        timeout=10)
    assert "starting" in result.output
    assert result.metadata["exit_code"] == 124
    assert "timed out" in result.output


@pytest.mark.asyncio
async def test_bash_honors_cancel_before_start(tmp_path):
    tool = BashTool()
    ctx = _ctx(tmp_path)
    ctx.cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await tool.execute(BashParams(command="echo nope"), ctx)


@pytest.mark.asyncio
async def test_bash_honors_cancel_mid_execution(tmp_path):
    tool = BashTool()
    ctx = _ctx(tmp_path)

    async def _cancel_soon():
        await asyncio.sleep(0.1)
        ctx.cancel.set()

    asyncio.create_task(_cancel_soon())
    with pytest.raises(asyncio.CancelledError):
        await tool.execute(BashParams(command="sleep 5"), ctx)


@pytest.mark.asyncio
async def test_bash_truncates_long_output(tmp_path):
    tool = BashTool()
    # Generate >30000 chars of output.
    result = await tool.execute(
        BashParams(command="python3 -c 'print(\"x\" * 40000)'"), _ctx(tmp_path)
    )
    assert "[output truncated" in result.output


@pytest.mark.asyncio
async def test_bash_rejects_timeout_over_limit(tmp_path):
    with pytest.raises(ValueError):
        BashParams(command="echo", timeout=601)


@pytest.mark.asyncio
async def test_bash_background_returns_live_pid(tmp_path):
    tool = BashTool()
    # A process that stays alive well past the grace window.
    result = await tool.execute(
        BashParams(command="sleep 30", background=True), _ctx(tmp_path)
    )
    assert "[running pid" in result.output
    assert result.metadata["background"] is True
    assert result.metadata["alive"] is True
    pid = int(result.metadata["pid"])
    # Still alive after execute() returned — it was NOT killed.
    os.kill(pid, 0)  # raises if dead
    os.kill(pid, signal.SIGKILL)  # cleanup


@pytest.mark.asyncio
async def test_bash_background_surfaces_startup_crash(tmp_path):
    tool = BashTool()
    # Writes to stderr then exits immediately — mimics "Address already in use".
    result = await tool.execute(
        BashParams(command="echo boom 1>&2; exit 1", background=True), _ctx(tmp_path)
    )
    assert "[exited within" in result.output
    assert "boom" in result.output  # the crash output is visible to the model
    assert result.metadata["alive"] is False


@pytest.mark.asyncio
async def test_bash_background_survives_cancel(tmp_path):
    tool = BashTool()
    ctx = _ctx(tmp_path)
    result = await tool.execute(BashParams(command="sleep 30", background=True), ctx)
    pid = int(result.metadata["pid"])
    # Cancelling the turn AFTER a detached launch must not reap the child.
    ctx.cancel.set()
    await asyncio.sleep(0.2)
    os.kill(pid, 0)  # raises if the detached process was killed
    os.kill(pid, signal.SIGKILL)  # cleanup
