import asyncio
import pytest

from poor_code.domain.harness.node import AgentNode, NodeContext, NodeResult, _safe_args
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


class _ProbeWithMsgs(AgentNode):
    name = "probe"
    def build_messages(self, state):
        return [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


class _CacheProbeRead:
    """Records the read_cache the loop handed it via ToolContext."""
    id = "read"; description = "stub"; params = _ReadArgs
    def __init__(self): self.seen_cache = "unset"
    async def execute(self, args, ctx):
        self.seen_cache = ctx.read_cache
        class R: output = "FILE BODY of " + args.path
        return R()


class _OneReadThenTerminalLLM:
    """Round 1: a 'read a.py' call. Round 2: the terminal 'finish' call."""
    def __init__(self): self.round = 0
    async def stream(self, messages, tools, response_format=None):
        self.round += 1
        if self.round == 1:
            yield ToolCallStarted(call_id="a1", name="read")
            yield ToolCallInputDelta(call_id="a1", json_delta='{"path":"a.py"}')
            yield ToolCallEnded(call_id="a1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield ToolCallStarted(call_id="t1", name="finish")
            yield ToolCallInputDelta(call_id="t1", json_delta='{"ok":true}')
            yield ToolCallEnded(call_id="t1")
            yield FinishedReason(reason="tool_calls")


class _FinishCompletion:
    def terminal_tool(self):
        return {"type": "function", "function": {
            "name": "finish",
            "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}}
    def output_model(self): return None
    def extract(self, raw, ctx): return NodeResult(output="DONE")


@pytest.mark.asyncio
async def test_decide_with_tools_threads_session_read_cache_into_tools():
    """The loop hands the Driver's session-scoped ReadCache to each tool via ToolContext
    (read dedup lives in the Read tool, keyed on that shared cache). Without a runtime the
    cache is None (dedup off)."""
    from poor_code.domain.harness.driver import DriverRuntime
    rt = DriverRuntime()
    node = _ProbeWithMsgs(_OneReadThenTerminalLLM())
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event(), runtime=rt)
    tool = _CacheProbeRead()
    result = await node._decide_with_tools(ctx, _FinishCompletion(), ToolRegistry([tool]))
    assert result.output == "DONE"
    assert tool.seen_cache is rt.read_cache   # the session cache reached the tool


@pytest.mark.asyncio
async def test_read_loop_threads_cwd_into_tool_context(tmp_path):
    """_read_loop must run tools in the cwd it is given, not Path.cwd()."""
    seen = {}

    class _CwdProbeTool:
        id = "probe"; description = "stub"; params = _ReadArgs
        async def execute(self, args, ctx):
            seen["cwd"] = ctx.cwd
            class R: output = "ok"
            return R()

    class _CallProbeThenStop:
        def __init__(self): self.round = 0
        async def stream(self, messages, tools, response_format=None):
            self.round += 1
            if self.round == 1:
                yield ToolCallStarted(call_id="p1", name="probe")
                yield ToolCallInputDelta(call_id="p1", json_delta="{}")
                yield ToolCallEnded(call_id="p1")
                yield FinishedReason(reason="tool_calls")
            else:
                yield FinishedReason(reason="stop")

    node = _Probe(_CallProbeThenStop())
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    await node._read_loop(ctx, ToolRegistry([_CwdProbeTool()]),
                          [{"role": "system", "content": "s"},
                           {"role": "user", "content": "u"}],
                          cwd=tmp_path)
    assert seen["cwd"] == tmp_path
