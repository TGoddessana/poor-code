import asyncio
from pathlib import Path

from pydantic import BaseModel

from poor_code.domain.tool.base import (
    ExecuteResult,
    PermissionRequest,
    Tool,
    ToolContext,
)


def test_execute_result_defaults():
    r = ExecuteResult(title="t", output="o")
    assert r.metadata == {}


def test_tool_context_fields():
    ev = asyncio.Event()
    async def stub_ask(req): return "allow"
    ctx = ToolContext(
        turn_id="T1", cancel=ev, cwd=Path("/tmp"), ask=stub_ask,
    )
    assert ctx.turn_id == "T1"
    assert ctx.cancel is ev
    assert ctx.cwd == Path("/tmp")


def test_permission_request_carries_tool_id_and_pattern():
    req = PermissionRequest(tool_id="read", pattern="/etc/*")
    assert req.tool_id == "read"
    assert req.pattern == "/etc/*"
    assert req.metadata == {}


def test_tool_protocol_runtime_checkable():
    class Args(BaseModel): pass
    class DummyTool:
        id = "dummy"
        description = "d"
        params = Args
        async def execute(self, args, ctx): return ExecuteResult(title="t", output="o")
    assert isinstance(DummyTool(), Tool)
