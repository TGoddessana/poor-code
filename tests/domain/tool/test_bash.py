import asyncio
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
async def test_bash_timeout_raises(tmp_path):
    tool = BashTool()
    with pytest.raises(TimeoutError, match="timed out"):
        await tool.execute(BashParams(command="sleep 5", timeout=1), _ctx(tmp_path))


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
