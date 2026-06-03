import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.acceptance_critic import AcceptanceCritic
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Layer, Requirement, SessionState, Transition,
    TriggerKind, VerdictKind,
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


def _state(history=()):
    return SessionState(
        requirement=Requirement(summary="create hello.txt with 'Hello, world!\\n'"),
        acceptance=AcceptanceSpec(checks=(
            AcceptanceCheck(criterion="content", command="grep -q Hello hello.txt"),)),
        history=history,
    )


@pytest.mark.asyncio
async def test_advances_when_adequate():
    llm = FakeLLM({"adequate": True, "counterexample": None})
    res = await AcceptanceCritic(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_repairs_with_counterexample():
    llm = FakeLLM({"adequate": False,
                   "counterexample": "echo 'Hello, mars!' > hello.txt passes grep but is wrong"})
    res = await AcceptanceCritic(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.ACCEPTANCE
    assert "mars" in res.verdict.hint


@pytest.mark.asyncio
async def test_critic_prompt_includes_the_checks():
    llm = FakeLLM({"adequate": True})
    await AcceptanceCritic(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "grep -q Hello hello.txt" in prompt


def _bounces(n):
    return tuple(
        Transition(from_node="acceptance_critic", to_node="acceptance_oracle",
                   trigger=TriggerKind.GATE, reason="r", ts_iso="t")
        for _ in range(n))


@pytest.mark.asyncio
async def test_repairs_well_under_budget():
    # Budget is now 100 — a handful of prior bounces must still REPAIR, not escalate.
    llm = FakeLLM({"adequate": False, "counterexample": "still bad"})
    res = await AcceptanceCritic(llm).run(
        NodeContext(_state(history=_bounces(5)), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR


@pytest.mark.asyncio
async def test_escalates_after_budget():
    from poor_code.domain.harness.nodes.gates import ACCEPTANCE_REPAIR_BUDGET
    assert ACCEPTANCE_REPAIR_BUDGET == 100
    llm = FakeLLM({"adequate": False, "counterexample": "still bad"})
    res = await AcceptanceCritic(llm).run(
        NodeContext(_state(history=_bounces(ACCEPTANCE_REPAIR_BUDGET)),
                    cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ESCALATE
