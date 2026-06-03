import asyncio
import json
import pytest
from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.router import Router
from poor_code.domain.session.models import SessionState, Request, RequestKind
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class FakeLLMClient:
    """Emits one tool call whose args JSON is the canned classification."""
    def __init__(self, args_obj):
        self._args = json.dumps(args_obj)

    async def stream(self, messages, tools, response_format=None):
        assert len(tools) == 1
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=self._args)
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


class SilentLLMClient:
    """Never calls the output tool — exercises the deterministic fallback."""
    async def stream(self, messages, tools, response_format=None):
        yield FinishedReason(reason="stop")


def _state(text):
    return SessionState(request=Request(raw_text=text, kind=RequestKind.ENGINEERING))


@pytest.mark.asyncio
async def test_router_classifies_korean_greeting_as_lightweight():
    # The deterministic seed cannot catch this; the LLM classifier can.
    node = Router(FakeLLMClient({"kind": "lightweight", "reason": "greeting"}))
    res = await node.run(NodeContext(state=_state("반갑다 너는 누구냐"), cancel=asyncio.Event()))
    assert isinstance(res.output, Request)
    assert res.output.kind is RequestKind.LIGHTWEIGHT
    assert res.output.raw_text == "반갑다 너는 누구냐"


@pytest.mark.asyncio
async def test_router_classifies_engineering_request():
    node = Router(FakeLLMClient({"kind": "engineering", "reason": "code change"}))
    res = await node.run(NodeContext(state=_state("리팩터링 해줘"), cancel=asyncio.Event()))
    assert res.output.kind is RequestKind.ENGINEERING
    assert res.output.raw_text == "리팩터링 해줘"


@pytest.mark.asyncio
async def test_router_output_tool_schema_names_kind():
    node = Router(FakeLLMClient({"kind": "engineering", "reason": "x"}))
    tool = node.output_tool()
    assert "kind" in tool["function"]["parameters"]["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text,kind", [
    ("hi there", RequestKind.LIGHTWEIGHT),
    ("", RequestKind.LIGHTWEIGHT),
    ("add oauth login to the api", RequestKind.ENGINEERING),  # conservative default
])
async def test_router_falls_back_to_seed_when_llm_silent(text, kind):
    node = Router(SilentLLMClient())
    res = await node.run(NodeContext(state=_state(text), cancel=asyncio.Event()))
    assert res.output.kind is kind
    assert res.output.raw_text == text
