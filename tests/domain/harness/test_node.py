import asyncio
import pytest
from poor_code.domain.harness.node import Node, NodeResult, NodeContext
from poor_code.domain.session.models import SessionState, CodeContext


class _Echo:
    name = "echo"
    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=CodeContext())


def test_noderesult_defaults():
    r = NodeResult(output=None)
    assert r.output is None and r.verdict is None


@pytest.mark.asyncio
async def test_node_protocol_runs():
    node = _Echo()
    assert isinstance(node, Node)
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    result = await node.run(ctx)
    assert isinstance(result.output, CodeContext)


def test_node_result_can_carry_query():
    from poor_code.domain.harness.node import NodeResult
    from poor_code.domain.session.models import Query, QueryKind
    q = Query(id="q1", kind=QueryKind.CLARIFY, prompt="?")
    r = NodeResult(query=q)
    assert r.query is q
    assert r.output is None and r.verdict is None


import json
from poor_code.domain.harness.node import AgentNode
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class _CaptureLLM:
    def __init__(self):
        self.seen_messages = None
    async def stream(self, messages, tools):
        self.seen_messages = messages
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


@pytest.mark.asyncio
async def test_dispatch_inserts_extra_messages_after_system():
    llm = _CaptureLLM()
    node = _Probe(llm)
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    extra = [{"role": "assistant", "content": "explored"}]
    await node._dispatch(ctx, extra_messages=extra)
    roles = [m["role"] for m in llm.seen_messages]
    assert roles == ["system", "assistant", "user"]  # extra after system, before user
