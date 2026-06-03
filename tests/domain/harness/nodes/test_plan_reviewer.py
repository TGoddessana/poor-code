import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.plan_reviewer import (
    PlanReviewer,
    _plan_review_repair_count,
)
from poor_code.domain.session.models import (
    CodeContext,
    EditScope,
    Layer,
    Plan,
    Requirement,
    SessionState,
    Task,
    Transition,
    TriggerKind,
    VerdictKind,
)
from poor_code.provider.events import (
    FinishedReason,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
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


def _state(plan: Plan, history=()):
    return SessionState(
        requirement=Requirement(summary="fibonacci HTTP server on :3000"),
        plan=plan,
        history=history,
    )


def _plan():
    return Plan(
        tasks=(
            Task(id="t1", title="server", purpose="serve",
                 edit_scope=EditScope(editable=("server.py",)),
                 how_to_validate="curl -fs localhost:3000/fib/10 | grep -qx 55"),
        ),
        deps=(),
    )


@pytest.mark.asyncio
async def test_clean_plan_advances():
    llm = FakeLLM({"ok": True})
    res = await PlanReviewer(llm).run(NodeContext(_state(_plan()), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_pathology_repairs_to_planner():
    llm = FakeLLM({"ok": False, "violation": "over-decomposition: t1 and t2 are one unit"})
    res = await PlanReviewer(llm).run(NodeContext(_state(_plan()), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN
    assert "over-decomposition" in res.verdict.hint


@pytest.mark.asyncio
async def test_prompt_carries_plan_requirement_and_environment():
    # environment lives on CodeContext so the reviewer can judge runtime fit.
    llm = FakeLLM({"ok": True})
    state = SessionState(
        requirement=Requirement(summary="fib server"),
        plan=_plan(),
        understanding=CodeContext(environment="python3: present; node: NOT FOUND"),
    )
    await PlanReviewer(llm).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "server.py" in prompt
    assert "fib server" in prompt
    assert "NOT FOUND" in prompt


@pytest.mark.asyncio
async def test_convergence_cap_advances_after_two_repairs():
    # Two prior plan_reviewer -> planner bounces already in history.
    bounce = Transition(from_node="plan_reviewer", to_node="planner",
                        trigger=TriggerKind.GATE, reason="x", ts_iso="2026-06-04T00:00:00Z")
    history = (bounce, bounce)
    llm = FakeLLM({"ok": False, "violation": "still too many tasks"})
    res = await PlanReviewer(llm).run(
        NodeContext(_state(_plan(), history=history), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ADVANCE


def test_repair_counter_counts_only_plan_reviewer_bounces():
    rv = Transition(from_node="plan_reviewer", to_node="planner",
                    trigger=TriggerKind.GATE, reason="x", ts_iso="t")
    gate = Transition(from_node="plan_gate", to_node="planner",
                      trigger=TriggerKind.GATE, reason="x", ts_iso="t")
    state = SessionState(history=(rv, gate, rv))
    assert _plan_review_repair_count(state) == 2
