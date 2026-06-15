import asyncio
import pytest
from poor_code.domain.harness.node import AgentNode, NodeContext
from poor_code.domain.session.models import SessionState
from poor_code.provider.events import (
    TextDelta, ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class _EchoToolLLM:
    """Echoes which tool name it was given, as the tool-call args."""
    def __init__(self): self.seen_tool_names = None
    async def stream(self, messages, tools, response_format=None):
        self.seen_tool_names = [t["function"]["name"] for t in tools]
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta='{"ok": true}')
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


class _Probe(AgentNode):
    name = "probe"
    def output_tool(self):
        return {"type": "function",
                "function": {"name": "default_tool", "parameters": {"type": "object"}}}


@pytest.mark.asyncio
async def test_stream_once_uses_default_tool_when_none_given():
    llm = _EchoToolLLM()
    node = _Probe(llm)
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    raw = await node._stream_once(ctx, [{"role": "user", "content": "x"}], None)
    assert llm.seen_tool_names == ["default_tool"]
    assert raw == '{"ok": true}'


@pytest.mark.asyncio
async def test_stream_once_uses_explicit_tool_when_given():
    llm = _EchoToolLLM()
    node = _Probe(llm)
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    custom = {"type": "function",
              "function": {"name": "custom_tool", "parameters": {"type": "object"}}}
    raw = await node._stream_once(ctx, [{"role": "user", "content": "x"}], None, tool=custom)
    assert llm.seen_tool_names == ["custom_tool"]


from poor_code.domain.harness.node import Completion, StructuredCompletion, NodeResult
from pydantic import BaseModel


class _Out(BaseModel):
    value: str


def test_structured_completion_extracts_via_parse():
    tool = {"type": "function",
            "function": {"name": "emit", "parameters": _Out.model_json_schema()}}
    comp = StructuredCompletion(
        tool=tool, model=_Out, parse=lambda raw: {"parsed": raw})
    assert comp.terminal_tool() is tool
    assert comp.output_model() is _Out
    res = comp.extract('{"value": "hi"}', ctx=None)
    assert isinstance(res, NodeResult)
    assert res.output == {"parsed": '{"value": "hi"}'}


def test_structured_completion_is_a_completion():
    # Protocol conformance: the three methods exist with the right shapes.
    comp = StructuredCompletion(tool={"function": {"name": "e"}}, model=None,
                                parse=lambda raw: raw)
    assert isinstance(comp, Completion)


from poor_code.domain.harness.node import StructuredOutputError


class _SemanticRerollLLM:
    """Round 1: emits a payload extract() will reject. Round 2: a good one."""
    def __init__(self): self.round = 0
    async def stream(self, messages, tools, response_format=None):
        self.round += 1
        payload = '{"value": "bad"}' if self.round == 1 else '{"value": "good"}'
        yield ToolCallStarted(call_id="c", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c", json_delta=payload)
        yield ToolCallEnded(call_id="c")
        yield FinishedReason(reason="tool_calls")


class _PickyCompletion:
    """Accepts only value=='good'; rejects others to force a re-roll."""
    def terminal_tool(self):
        return {"type": "function", "function": {"name": "emit",
                "parameters": {"type": "object",
                               "properties": {"value": {"type": "string"}}}}}
    def output_model(self): return None
    def extract(self, raw, ctx):
        import json
        if json.loads(raw)["value"] != "good":
            raise StructuredOutputError("probe", raw, "value must be 'good'")
        return NodeResult(output="accepted")


class _TerminalProbe(AgentNode):
    name = "probe"
    def build_messages(self, state):
        return [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


@pytest.mark.asyncio
async def test_terminal_rerolls_until_extract_accepts():
    llm = _SemanticRerollLLM()
    node = _TerminalProbe(llm)
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    res = await node._terminal(ctx, _PickyCompletion())
    assert res.output == "accepted"
    assert llm.round == 2   # re-rolled once on the semantic rejection


class _GoodFirstTryLLM:
    def __init__(self): self.round = 0
    async def stream(self, messages, tools, response_format=None):
        self.round += 1
        yield ToolCallStarted(call_id="c", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c", json_delta='{"value": "good"}')
        yield ToolCallEnded(call_id="c")
        yield FinishedReason(reason="tool_calls")


@pytest.mark.asyncio
async def test_terminal_happy_path_single_attempt():
    llm = _GoodFirstTryLLM()
    node = _TerminalProbe(llm)
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    res = await node._terminal(ctx, _PickyCompletion())
    assert res.output == "accepted"
    assert llm.round == 1   # accepted on the first attempt, no re-roll


class _ContentOnlyLLM:
    """Returns the structured object as CONTENT (no tool call), as happens under
    response_format on some providers."""
    async def stream(self, messages, tools, response_format=None):
        yield TextDelta(text='{"value": "good"}')
        yield FinishedReason(reason="stop")


class _ModelCompletion:
    """Has an output_model — so content-only output must be accepted via the
    completion's model even when the node itself defines no output_model."""
    def terminal_tool(self):
        return {"type": "function", "function": {"name": "emit",
                "parameters": {"type": "object",
                               "properties": {"value": {"type": "string"}}}}}
    def output_model(self): return _Out
    def extract(self, raw, ctx):
        import json
        return NodeResult(output=json.loads(raw)["value"])


@pytest.mark.asyncio
async def test_terminal_accepts_content_via_completion_model():
    # _TerminalProbe.output_model() is the base default (None); the COMPLETION supplies
    # the model. Content-only output must still be accepted (regression: _stream_once
    # used to check self.output_model(), wrongly rejecting this).
    node = _TerminalProbe(_ContentOnlyLLM())
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    res = await node._terminal(ctx, _ModelCompletion())
    assert res.output == "good"
