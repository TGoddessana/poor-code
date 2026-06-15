import asyncio
import pytest
from poor_code.domain.harness.node import AgentNode, NodeContext
from poor_code.domain.session.models import SessionState
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
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
