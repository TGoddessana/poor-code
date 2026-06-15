import asyncio
import pytest

from poor_code.domain.harness.node import AgentNode, NodeContext, _safe_args
from poor_code.domain.session.models import SessionState
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    TextDelta, ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)
from pydantic import BaseModel


class _OneToolThenStopLLM:
    """Round 1: a 'read' tool call. Round 2: text only, no tool call."""
    def __init__(self): self.round = 0
    async def stream(self, messages, tools, response_format=None):
        self.round += 1
        if self.round == 1:
            yield TextDelta(text="looking ")
            yield ToolCallStarted(call_id="r1", name="read")
            yield ToolCallInputDelta(call_id="r1", json_delta='{"path":"a.py"}')
            yield ToolCallEnded(call_id="r1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield TextDelta(text="done thinking")
            yield FinishedReason(reason="stop")


class _ReadArgs(BaseModel):
    path: str = ""


class _ReadStub:
    id = "read"; description = "stub"; params = _ReadArgs
    async def execute(self, args, ctx):
        class R: output = "FILE BODY of " + args.path
        return R()


class _Probe(AgentNode):
    name = "probe"


@pytest.mark.asyncio
async def test_stream_tools_returns_text_and_calls():
    node = _Probe(_OneToolThenStopLLM())
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    text, calls = await node._stream_tools(ctx, [{"role": "user", "content": "hi"}],
                                            ToolRegistry([_ReadStub()]).schemas())
    assert "looking" in text
    assert calls == [("r1", "read", '{"path":"a.py"}')]


@pytest.mark.asyncio
async def test_run_tool_executes_and_errors_gracefully():
    node = _Probe(_OneToolThenStopLLM())
    reg = ToolRegistry([_ReadStub()])
    from poor_code.domain.tool.base import ToolContext, allow_all
    from pathlib import Path
    tctx = ToolContext(turn_id="probe", cancel=asyncio.Event(), cwd=Path.cwd(), ask=allow_all)
    ok = await node._run_tool(reg, "read", '{"path":"a.py"}', tctx)
    assert ok == "FILE BODY of a.py"
    missing = await node._run_tool(reg, "nope", "{}", tctx)
    assert missing.startswith("ERROR: unknown tool nope")


def test_safe_args_parses_or_empties():
    assert _safe_args('{"path":"a.py"}') == {"path": "a.py"}
    assert _safe_args("not json") == {}
    assert _safe_args("[1, 2]") == {"_": [1, 2]}   # non-dict JSON is wrapped
