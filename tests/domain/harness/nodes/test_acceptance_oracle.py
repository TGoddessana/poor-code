import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.acceptance_oracle import AcceptanceOracle
from poor_code.domain.session.models import (
    AcceptanceSpec, CodeContext, GroundingStatus, Request, RequestKind,
    Requirement, SessionState,
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
async def test_oracle_falls_back_to_request_when_requirement_absent():
    # Headless (FULL_AUTO) skips the interviewer, so state.requirement is None. The
    # oracle must ground its global done-check on the raw request (the issue text,
    # which carries the reproduction) instead of asserting — this is what makes the
    # check independent of the planner's self-authored per-task validations.
    issue = ("ascii.qdp assumes upper-case commands. "
             "Table.read of 'read serr 1 2' should not crash.")
    state = SessionState(
        requirement=None,
        request=Request(raw_text=issue, kind=RequestKind.ENGINEERING),
        understanding=CodeContext(grounding=GroundingStatus.GREENFIELD),
    )
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "read serr 1 2" in prompt  # the issue's reproduction reached the oracle


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
async def test_oracle_system_states_task_independent_anti_gaming_rules():
    # These are the three universal anti-gaming invariants (NOT task-specific):
    # exact-equality over substring, at least one non-example input (lookup-table
    # defence), and at least one boundary/extreme input.
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    system = llm.seen_messages[0]["content"].lower()
    assert "substring" in system          # exact-equality, not substring match
    assert "lookup" in system             # defend against lookup-table / hard-coded outputs
    assert "boundary" in system           # exercise extreme / edge inputs


@pytest.mark.asyncio
async def test_oracle_surfaces_repair_hint_forcefully():
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(
        NodeContext(_state(repair_hint="a 13-byte file with no newline passes — wrong"),
                    cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "13-byte file with no newline" in prompt
    # the counterexample must be framed as something the redesign has to DEFEAT
    assert "counterexample" in prompt.lower()
    assert "fail" in prompt.lower()
