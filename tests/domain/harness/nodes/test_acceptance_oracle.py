import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.acceptance_oracle import AcceptanceOracle
from poor_code.domain.session.models import (
    AcceptanceSpec, CodeContext, GroundingStatus, Requirement, SessionState,
)
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.seen_messages = None

    async def stream(self, messages, tools, response_format=None):
        self.seen_messages = messages
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=json.dumps(self.payload))
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _state(repair_hint=None):
    return SessionState(
        requirement=Requirement(
            summary="create hello.txt containing 'Hello, world!\\n'",
            acceptance=("hello.txt has exact content",),
        ),
        understanding=CodeContext(grounding=GroundingStatus.GREENFIELD),
        repair_hint=repair_hint,
    )


@pytest.mark.asyncio
async def test_oracle_emits_acceptance_spec():
    llm = FakeLLM({"checks": [
        {"criterion": "exact content", "command": "printf 'Hello, world!\\n' | diff - hello.txt",
         "rationale": "content equality, no derived metric"}]})
    res = await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    assert isinstance(res.output, AcceptanceSpec)
    assert res.output.checks[0].criterion == "exact content"
    assert "diff - hello.txt" in res.output.checks[0].command


@pytest.mark.asyncio
async def test_oracle_prompt_includes_requirement_and_grounding_rules():
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    system = llm.seen_messages[0]["content"]
    assert "create hello.txt" in prompt
    assert "hello.txt has exact content" in prompt
    assert "content" in system.lower() and "diff" in system.lower()


@pytest.mark.asyncio
async def test_oracle_surfaces_repair_hint():
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(
        NodeContext(_state(repair_hint="a 13-byte file with no newline passes — wrong"),
                    cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "13-byte file with no newline" in prompt
