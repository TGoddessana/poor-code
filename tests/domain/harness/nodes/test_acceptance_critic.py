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
async def test_repairs_when_inadequate_under_cap():
    # Below the convergence cap, an inadequate verdict still bounces back to the oracle.
    llm = FakeLLM({"adequate": False, "counterexample": "still bad"})
    res = await AcceptanceCritic(llm).run(
        NodeContext(_state(history=_bounces(2)), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR


@pytest.mark.asyncio
async def test_advances_on_gate_valid_spec_after_convergence_cap():
    # The critic's "can you break it?" is unbounded — a finite check set is always
    # theoretically gameable, so it can loop forever. After CONVERGENCE_CAP bounces
    # we accept the gate-valid spec and move on (forward progress beats abandoning).
    from poor_code.domain.harness.nodes.acceptance_critic import _CONVERGENCE_CAP
    assert _CONVERGENCE_CAP == 3
    llm = FakeLLM({"adequate": False, "counterexample": "still theoretically gameable"})
    res = await AcceptanceCritic(llm).run(
        NodeContext(_state(history=_bounces(_CONVERGENCE_CAP)), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ADVANCE


def test_prompt_has_bounded_adequacy_bar():
    from poor_code.domain.harness.nodes.acceptance_critic import _SYSTEM
    s = _SYSTEM.lower()
    # the finite bar the oracle is also told to satisfy
    assert "exact" in s and "substring" in s
    assert "boundary" in s
    # must forbid the unfalsifiable "finite checks are theoretically gameable" rejection
    assert "do not reject" in s or "not grounds" in s or "must set adequate" in s
