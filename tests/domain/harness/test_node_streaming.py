import asyncio
import json
import pytest
from poor_code.domain.harness.node import AgentNode, NodeContext
from poor_code.domain.session.models import SessionState
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)


class _LLM:
    async def stream(self, messages, tools, response_format=None):
        yield TextDelta(text="think ")
        yield TextDelta(text="hard")
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta="{}")
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


class _Probe(AgentNode):
    name = "probe"
    def build_messages(self, state):
        return [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    def output_tool(self):
        return {"type": "function", "function": {"name": "out", "parameters": {}}}
    def parse(self, args_json):
        return json.loads(args_json)


class _Sink:
    def __init__(self):
        self.texts = []
    def node_thinking_delta(self, node, t):
        self.texts.append(t)
    def node_context(self, node, phase, messages):
        pass
    def node_raw_output(self, node, raw):
        pass


@pytest.mark.asyncio
async def test_dispatch_streams_text_to_sink():
    sink = _Sink()
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event(), sink=sink)
    await _Probe(_LLM())._dispatch(ctx)
    # Both prose deltas AND the tool-call input JSON now stream as thinking.
    assert sink.texts == ["think ", "hard", "{}"]


@pytest.mark.asyncio
async def test_dispatch_without_sink_does_not_crash():
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    out = await _Probe(_LLM())._dispatch(ctx)
    assert out == "{}"
