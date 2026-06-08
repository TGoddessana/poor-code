import asyncio
import pytest
from pydantic import BaseModel
from poor_code.domain.harness.node import AgentNode, NodeContext
from poor_code.domain.session.models import SessionState, Cursor, Phase
from poor_code.provider.events import ToolCallStarted, ToolCallInputDelta, ToolCallEnded


class _Out(BaseModel):
    q: str


class _FakeLLM:
    async def stream(self, messages, tools, response_format=None):
        yield ToolCallStarted(call_id="c1", name="emit")
        yield ToolCallInputDelta(call_id="c1", json_delta='{"q":')
        yield ToolCallInputDelta(call_id="c1", json_delta='"why"}')
        yield ToolCallEnded(call_id="c1")


class _Node(AgentNode):
    name = "interviewer"
    def build_messages(self, state):
        return [{"role": "system", "content": "ask"}, {"role": "user", "content": "hi"}]
    def output_tool(self):
        return {"function": {"name": "emit", "parameters": {"type": "object"}}}
    def output_model(self):
        return _Out
    def parse(self, args_json):
        return _Out.model_validate_json(args_json)


class _RecSink:
    def __init__(self):
        self.thinking, self.contexts, self.raw = [], [], []
    def node_context(self, node, phase, messages): self.contexts.append((node, len(messages)))
    def node_thinking_delta(self, node, text): self.thinking.append((node, text))
    def node_raw_output(self, node, raw): self.raw.append((node, raw))


@pytest.mark.asyncio
async def test_node_streams_toolcall_json_as_thinking_and_captures_io():
    sink = _RecSink()
    state = SessionState(cursor=Cursor(phase=Phase.INTERVIEWING, current_node="interviewer"))
    ctx = NodeContext(state=state, cancel=asyncio.Event(), sink=sink)
    result = await _Node(_FakeLLM()).run(ctx)
    assert result.output.q == "why"
    assert sink.thinking == [("interviewer", '{"q":'), ("interviewer", '"why"}')]
    assert sink.contexts == [("interviewer", 2)]
    assert sink.raw == [("interviewer", '{"q":"why"}')]
