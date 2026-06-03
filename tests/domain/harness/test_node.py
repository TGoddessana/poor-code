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
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason, TextDelta,
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


# --- bounded re-roll when the model fails to produce structured output ---

from pydantic import BaseModel
from poor_code.domain.harness.node import (
    StructuredOutputError, MAX_DISPATCH_ATTEMPTS,
)


class _ProseLLM:
    """Endpoint that never calls the tool — only emits prose content. Models
    that narrate instead of calling the forced output tool look like this."""
    def __init__(self):
        self.calls = 0

    async def stream(self, messages, tools, response_format=None):
        self.calls += 1
        yield TextDelta(text="Sure, here is what I think...")
        yield FinishedReason(reason="stop")


class _FlakyLLM:
    """Narrates on the first attempt, then calls the tool on the second."""
    def __init__(self):
        self.calls = 0

    async def stream(self, messages, tools, response_format=None):
        self.calls += 1
        if self.calls == 1:
            yield TextDelta(text="hmm let me just explain instead")
            yield FinishedReason(reason="stop")
            return
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta='{"ok": 1}')
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


@pytest.mark.asyncio
async def test_dispatch_prefers_real_tool_calls():
    # When the endpoint returns a proper tool_call, that wins on the first try.
    out = await _Probe(_CaptureLLM())._dispatch(
        NodeContext(state=SessionState(), cancel=asyncio.Event()))
    assert out == "{}"


@pytest.mark.asyncio
async def test_dispatch_rerolls_until_tool_call_succeeds():
    # First attempt narrates (no tool call) → re-roll → second attempt succeeds.
    llm = _FlakyLLM()
    out = await _Probe(llm)._dispatch(
        NodeContext(state=SessionState(), cancel=asyncio.Event()))
    assert json.loads(out) == {"ok": 1}
    assert llm.calls == 2  # one re-roll, no more


@pytest.mark.asyncio
async def test_dispatch_raises_after_exhausting_attempts():
    # A model that always narrates exhausts the budget and raises (no recovery).
    llm = _ProseLLM()
    with pytest.raises(StructuredOutputError) as exc:
        await _Probe(llm)._dispatch(
            NodeContext(state=SessionState(), cancel=asyncio.Event()))
    assert llm.calls == MAX_DISPATCH_ATTEMPTS
    assert "no tool call" in exc.value.detail


class _SchemaModel(BaseModel):
    ok: int


class _BadArgsLLM:
    """Calls the tool but with schema-invalid args every time."""
    def __init__(self):
        self.calls = 0

    async def stream(self, messages, tools, response_format=None):
        self.calls += 1
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta='{"ok": "not-an-int-and-bad"}')
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


class _ValidatedProbe(_Probe):
    def output_model(self):
        return _SchemaModel


@pytest.mark.asyncio
async def test_dispatch_rerolls_on_schema_invalid_args():
    # output_model set → schema-invalid args are re-rolled, then surfaced raw.
    llm = _BadArgsLLM()
    with pytest.raises(StructuredOutputError) as exc:
        await _ValidatedProbe(llm)._dispatch(
            NodeContext(state=SessionState(), cancel=asyncio.Event()))
    assert llm.calls == MAX_DISPATCH_ATTEMPTS
    assert "ok" in exc.value.detail   # points at the bad field

