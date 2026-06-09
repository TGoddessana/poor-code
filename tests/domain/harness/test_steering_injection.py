import asyncio
import pytest

from poor_code.domain.harness.node import AgentNode, NodeContext
from poor_code.domain.session.models import SessionState
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)
from tests.provider.fakes import FakeLLMClient


class _ProbeNode(AgentNode):
    name = "probe"

    def build_messages(self, state):
        return [{"role": "system", "content": "sys"},
                {"role": "user", "content": "task"}]

    def output_tool(self):
        return {"function": {"name": "out", "parameters": {"type": "object"}}}

    def parse(self, args_json):
        return None


def _tool_round():
    return [[ToolCallStarted(call_id="c1", name="out"),
             ToolCallInputDelta(call_id="c1", json_delta="{}"),
             ToolCallEnded(call_id="c1"),
             FinishedReason(reason="stop")]]


@pytest.mark.asyncio
async def test_steering_notes_are_injected_into_llm_messages():
    llm = FakeLLMClient(_tool_round())
    node = _ProbeNode(llm)
    state = SessionState(steering_notes=("follow auth.py pattern",))
    await node.run(NodeContext(state=state, cancel=asyncio.Event()))
    sent = llm.calls[0]["messages"]
    contents = "\n".join(m["content"] for m in sent)
    assert "follow auth.py pattern" in contents
    # injected right after the system message, before the task message
    assert sent[0]["content"] == "sys"
    assert "steering" in sent[1]["content"].lower()


@pytest.mark.asyncio
async def test_no_steering_message_when_empty():
    llm = FakeLLMClient(_tool_round())
    node = _ProbeNode(llm)
    await node.run(NodeContext(state=SessionState(), cancel=asyncio.Event()))
    sent = llm.calls[0]["messages"]
    assert all("steering" not in m["content"].lower() for m in sent)
    assert len(sent) == 2  # system + task only
