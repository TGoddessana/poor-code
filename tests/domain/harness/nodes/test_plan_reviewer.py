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
async def test_convergence_cap_escalates_after_two_repairs():
    # At the cap the reviewer no longer ADVANCES a plan it still calls unsound (the
    # "consensus false progress" bug); it ESCALATES to the human (SUPERVISED-only path).
    bounce = Transition(from_node="plan_reviewer", to_node="planner",
                        trigger=TriggerKind.GATE, reason="x", ts_iso="2026-06-04T00:00:00Z")
    history = (bounce, bounce)
    llm = FakeLLM({"ok": False, "violation": "still too many tasks"})
    res = await PlanReviewer(llm).run(
        NodeContext(_state(_plan(), history=history), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ESCALATE
    assert res.verdict.query is not None and "unsound" in res.verdict.query.lower()


def test_reviewer_does_not_reject_for_empty_validate():
    # Regression: pathology #4 (BROKEN VALIDATION) used to reject tasks with an empty
    # how_to_validate, but the planner intentionally writes none (the acceptance_oracle
    # owns validation). The contradiction looped planner↔reviewer. The rule is gone.
    from poor_code.domain.harness.nodes.plan_reviewer import _SYSTEM
    low = _SYSTEM.lower()
    assert "broken validation" not in low
    assert "do not reject" in low and "validate field" in low


def test_repair_counter_counts_only_plan_reviewer_bounces():
    rv = Transition(from_node="plan_reviewer", to_node="planner",
                    trigger=TriggerKind.GATE, reason="x", ts_iso="t")
    gate = Transition(from_node="plan_gate", to_node="planner",
                      trigger=TriggerKind.GATE, reason="x", ts_iso="t")
    state = SessionState(history=(rv, gate, rv))
    assert _plan_review_repair_count(state) == 2


def test_reviewer_prompt_lists_steps_and_new_pathologies():
    from poor_code.domain.harness.nodes.plan_reviewer import _SYSTEM
    from poor_code.domain.session.models import Step, StepKind
    low = _SYSTEM.lower()
    assert "type-inconsistency" in low or "inconsistent" in low
    assert "coverage" in low
    step = Step(id="t1.s1", kind=StepKind.IMPL, file="server.py",
                body="def clear_layers():\n    pass")
    task = Task(id="t1", title="t", purpose="p",
                edit_scope=EditScope(editable=("server.py",)),
                how_to_validate="pytest -q", steps=(step,))
    msgs = PlanReviewer(FakeLLM({"ok": True})).build_messages(_state(Plan(tasks=(task,))))
    assert "clear_layers" in msgs[-1]["content"]
