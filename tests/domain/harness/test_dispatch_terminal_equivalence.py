import asyncio
import pytest
from pydantic import BaseModel

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, StructuredCompletion,
)
from poor_code.domain.session.models import SessionState
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class _Out(BaseModel):
    value: str


class _OneShotLLM:
    def __init__(self):
        self.calls = 0

    async def stream(self, messages, tools, response_format=None):
        self.calls += 1
        yield ToolCallStarted(call_id="c", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c", json_delta='{"value": "ok"}')
        yield ToolCallEnded(call_id="c")
        yield FinishedReason(reason="tool_calls")


class _Probe(AgentNode):
    name = "probe"

    def build_messages(self, state):
        return [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]

    def output_tool(self):
        return {"type": "function",
                "function": {"name": "emit", "parameters": _Out.model_json_schema()}}

    def output_model(self):
        return _Out

    def parse(self, args_json):
        return _Out.model_validate_json(args_json)


@pytest.mark.asyncio
async def test_dispatch_returns_validated_raw():
    node = _Probe(_OneShotLLM())
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    raw = await node._dispatch(ctx)
    assert raw == '{"value": "ok"}'


@pytest.mark.asyncio
async def test_terminal_over_node_hooks_matches_dispatch():
    node = _Probe(_OneShotLLM())
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    raw = await node._dispatch(ctx)

    node2 = _Probe(_OneShotLLM())
    ctx2 = NodeContext(state=SessionState(), cancel=asyncio.Event())
    comp = StructuredCompletion(tool=node2.output_tool(), model=node2.output_model(),
                                parse=node2.parse)
    res = await node2._terminal(ctx2, comp)
    assert isinstance(res, NodeResult)
    assert res.output == _Out.model_validate_json(raw)
