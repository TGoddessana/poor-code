import asyncio
import pytest
from pydantic import BaseModel

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, ToolLoopHooks, _DEFAULT_HOOKS,
)
from poor_code.domain.session.models import SessionState
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    TextDelta, ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class _Args(BaseModel):
    path: str = ""


class _EchoTool:
    id = "read"; description = "stub"; params = _Args
    async def execute(self, args, ctx):
        class R: output = "BODY:" + args.path
        return R()


class _CallThenStop:
    """Round 1: one 'read' call + thinking text. Round 2: no calls."""
    def __init__(self): self.round = 0
    async def stream(self, messages, tools, response_format=None):
        self.round += 1
        if self.round == 1:
            yield TextDelta(text="thinking ")
            yield ToolCallStarted(call_id="r1", name="read")
            yield ToolCallInputDelta(call_id="r1", json_delta='{"path":"a.py"}')
            yield ToolCallEnded(call_id="r1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield FinishedReason(reason="stop")


class _Probe(AgentNode):
    name = "probe"


class _RecordSink:
    def __init__(self): self.text = []; self.started = []; self.finished = []
    def node_thinking_delta(self, name, t): self.text.append(t)
    def tool_started(self, cid, name, args): self.started.append((cid, name))
    def tool_finished(self, cid, out): self.finished.append((cid, out))
    def tool_failed(self, cid, out): self.finished.append((cid, out))


@pytest.mark.asyncio
async def test_tool_loop_no_leak_by_default(tmp_path):
    node = _Probe(_CallThenStop())
    sink = _RecordSink()
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event(), sink=sink)
    out = await node._tool_loop(
        ctx, seed_messages=[{"role": "system", "content": "s"},
                            {"role": "user", "content": "u"}],
        tools=ToolRegistry([_EchoTool()]), cwd=tmp_path, max_iterations=5)
    assert sink.text == []
    assert sink.started == [("r1", "read")]
    assert out[0]["role"] == "user"
    assert any(m["role"] == "tool" and m["content"] == "BODY:a.py" for m in out)


@pytest.mark.asyncio
async def test_tool_loop_leaks_text_when_enabled(tmp_path):
    node = _Probe(_CallThenStop())
    sink = _RecordSink()
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event(), sink=sink)
    await node._tool_loop(
        ctx, seed_messages=[{"role": "system", "content": "s"},
                            {"role": "user", "content": "u"}],
        tools=ToolRegistry([_EchoTool()]), cwd=tmp_path, max_iterations=5,
        leak_text=True)
    assert sink.text == ["thinking "]


@pytest.mark.asyncio
async def test_tool_loop_clamp_and_record_and_after_round(tmp_path):
    node = _Probe(_CallThenStop())
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    recorded, rounds = [], []

    class _Hooks:
        def clamp(self, output): return output[:4]
        def record(self, name, args, output): recorded.append((name, output))
        async def before_loop(self): rounds.append("before")
        async def after_round(self, rnd): rounds.append(rnd.index)

    out = await node._tool_loop(
        ctx, seed_messages=[{"role": "system", "content": "s"},
                            {"role": "user", "content": "u"}],
        tools=ToolRegistry([_EchoTool()]), cwd=tmp_path, max_iterations=5,
        hooks=_Hooks())
    assert any(m["role"] == "tool" and m["content"] == "BODY" for m in out)
    assert recorded == [("read", "BODY:a.py")]
    assert rounds == ["before", 0]


@pytest.mark.asyncio
async def test_default_hooks_are_noops():
    from poor_code.domain.harness.node import _LoopRound
    assert _DEFAULT_HOOKS.clamp("short") == "short"
    assert _DEFAULT_HOOKS.record("read", "{}", "out") is None
    await _DEFAULT_HOOKS.before_loop()                      # must not raise
    rnd = _LoopRound(index=0, calls=[], tool_msgs={}, full_output={}, messages=[])
    await _DEFAULT_HOOKS.after_round(rnd)                   # must not raise
