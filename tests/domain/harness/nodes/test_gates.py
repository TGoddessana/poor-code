import asyncio

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.gates import PlanGate, UnderstandingGate
from poor_code.domain.session.models import (
    CodeContext, CodeRef, Dependency, EditScope, GroundingStatus, Layer, Plan,
    SessionState, Step, StepKind, Task, Transition, TriggerKind, VerdictKind,
)


def _ctx(state: SessionState) -> NodeContext:
    return NodeContext(state=state, cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_advances_when_candidates_present():
    cc = CodeContext(candidates=(CodeRef(file="a.py", symbol="x"),))
    res = await UnderstandingGate().run(_ctx(SessionState(understanding=cc)))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_advances_when_greenfield_even_without_candidates():
    cc = CodeContext(candidates=(), grounding=GroundingStatus.GREENFIELD)
    res = await UnderstandingGate().run(_ctx(SessionState(understanding=cc)))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_repairs_when_not_found_without_candidates():
    cc = CodeContext(candidates=(), grounding=GroundingStatus.NOT_FOUND)
    res = await UnderstandingGate().run(_ctx(SessionState(understanding=cc)))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.UNDERSTANDING


@pytest.mark.asyncio
async def test_repairs_understanding_when_no_candidates():
    res = await UnderstandingGate().run(_ctx(SessionState(understanding=CodeContext())))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.UNDERSTANDING


@pytest.mark.asyncio
async def test_escalates_after_repair_budget_exhausted():
    # A prior gate-triggered bounce back to the explorer already happened.
    prior = Transition(from_node="understanding_gate", to_node="explorer",
                       trigger=TriggerKind.GATE, reason="repair", ts_iso="t")
    state = SessionState(understanding=CodeContext(), history=(prior,))
    res = await UnderstandingGate().run(_ctx(state))
    assert res.verdict.kind is VerdictKind.ESCALATE


def _task(**overrides) -> Task:
    data = {
        "id": "t1",
        "title": "A",
        "purpose": "B",
        "edit_scope": EditScope(editable=("src/a.py",)),
        "how_to_validate": "pytest tests/test_a.py",
        "steps": (Step(id="t1.s1", kind=StepKind.IMPL, file="src/a.py",
                       body="x = 1", run="pytest tests/test_a.py", expected="PASS"),),
    }
    data.update(overrides)
    return Task(**data)


def _task_with_steps(steps, **kw) -> Task:
    return Task(id="t1", title="t", purpose="p",
                edit_scope=EditScope(editable=("x.py",)),
                how_to_validate="pytest -q", steps=tuple(steps), **kw)


@pytest.mark.asyncio
async def test_plan_gate_rejects_task_without_steps():
    assert "no steps" in PlanGate._invalid_hint(Plan(tasks=(_task_with_steps(()),)))


def test_plan_gate_rejects_empty_body_step():
    step = Step(id="t1.s1", kind=StepKind.IMPL, file="x.py", body="")
    hint = PlanGate._invalid_hint(Plan(tasks=(_task_with_steps((step,)),)))
    assert hint is not None and "empty body" in hint


def test_plan_gate_rejects_placeholder_body():
    step = Step(id="t1.s1", kind=StepKind.IMPL, file="x.py",
                body="def f():\n    # TODO: implement later\n    pass")
    hint = PlanGate._invalid_hint(Plan(tasks=(_task_with_steps((step,)),)))
    assert hint is not None and "placeholder" in hint


def test_plan_gate_rejects_step_file_outside_editable():
    step = Step(id="t1.s1", kind=StepKind.IMPL, file="other.py", body="x = 1")
    hint = PlanGate._invalid_hint(Plan(tasks=(_task_with_steps((step,)),)))
    assert hint is not None and "outside editable" in hint


def test_plan_gate_accepts_well_formed_steps():
    step = Step(id="t1.s1", kind=StepKind.IMPL, file="x.py", body="x = 1",
                run="pytest -q", expected="PASS")
    assert PlanGate._invalid_hint(Plan(tasks=(_task_with_steps((step,)),))) is None


@pytest.mark.asyncio
async def test_plan_gate_advances_valid_plan():
    res = await PlanGate().run(_ctx(SessionState(plan=Plan(tasks=(_task(),)))))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_plan_gate_repairs_empty_plan():
    res = await PlanGate().run(_ctx(SessionState(plan=Plan())))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_plan_gate_repairs_missing_edit_scope_or_validation():
    res = await PlanGate().run(_ctx(SessionState(plan=Plan(tasks=(
        _task(edit_scope=EditScope(), how_to_validate=""),
    )))))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert "editable" in res.verdict.hint


@pytest.mark.asyncio
async def test_plan_gate_repairs_bad_dependency_reference():
    plan = Plan(tasks=(_task(),), deps=(Dependency(task_id="t1", depends_on="missing"),))
    res = await PlanGate().run(_ctx(SessionState(plan=plan)))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert "dependency" in res.verdict.hint


@pytest.mark.asyncio
async def test_plan_gate_repairs_dependency_cycle():
    t1 = _task(id="t1")
    t2 = _task(id="t2")
    plan = Plan(tasks=(t1, t2), deps=(
        Dependency(task_id="t1", depends_on="t2"),
        Dependency(task_id="t2", depends_on="t1"),
    ))
    res = await PlanGate().run(_ctx(SessionState(plan=plan)))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert "cycle" in res.verdict.hint


@pytest.mark.asyncio
async def test_plan_gate_escalates_after_repair_budget_exhausted():
    prior = Transition(from_node="plan_gate", to_node="planner",
                       trigger=TriggerKind.GATE, reason="repair", ts_iso="t")
    res = await PlanGate().run(_ctx(SessionState(plan=Plan(), history=(prior, prior))))
    assert res.verdict.kind is VerdictKind.ESCALATE


@pytest.mark.asyncio
async def test_plan_gate_rejects_too_many_editable_files():
    res = await PlanGate().run(_ctx(SessionState(plan=Plan(tasks=(
        _task(edit_scope=EditScope(editable=("a.py", "b.py", "c.py", "d.py"))),
    )))))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert "split" in res.verdict.hint.lower()


@pytest.mark.asyncio
async def test_plan_gate_rejects_prose_validation():
    res = await PlanGate().run(_ctx(SessionState(plan=Plan(tasks=(
        _task(how_to_validate="Check that the server returns 55."),
    )))))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert "command" in res.verdict.hint.lower()


@pytest.mark.asyncio
async def test_plan_gate_accepts_runnable_validation():
    res = await PlanGate().run(_ctx(SessionState(plan=Plan(tasks=(
        _task(how_to_validate="curl -s localhost:3000/fib/10 | grep -q 55"),
    )))))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_plan_gate_allows_two_repairs_before_escalating():
    one = Transition(from_node="plan_gate", to_node="planner",
                     trigger=TriggerKind.GATE, reason="r", ts_iso="t")
    # 1 prior bounce → still REPAIR (budget is 2)
    res1 = await PlanGate().run(_ctx(SessionState(plan=Plan(), history=(one,))))
    assert res1.verdict.kind is VerdictKind.REPAIR
    # 2 prior bounces → ESCALATE
    res2 = await PlanGate().run(_ctx(SessionState(plan=Plan(), history=(one, one))))
    assert res2.verdict.kind is VerdictKind.ESCALATE


@pytest.mark.asyncio
async def test_understanding_gate_repair_hint_uses_search_notes():
    state = SessionState(understanding=CodeContext(
        candidates=(), search_notes="grep reconnect 0건; try stream/close"))
    res = await UnderstandingGate().run(_ctx(state))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.UNDERSTANDING
    assert "stream/close" in res.verdict.hint


@pytest.mark.asyncio
async def test_understanding_gate_falls_back_when_no_notes():
    res = await UnderstandingGate().run(
        _ctx(SessionState(understanding=CodeContext(candidates=()))))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.hint  # non-empty fallback


@pytest.mark.asyncio
async def test_understanding_gate_escalates_after_explorer_bounce():
    state = SessionState(
        understanding=CodeContext(candidates=()),
        history=(Transition(from_node="understanding_gate", to_node="explorer",
                            trigger=TriggerKind.GATE, reason="r", ts_iso="t"),),
    )
    res = await UnderstandingGate().run(_ctx(state))
    assert res.verdict.kind is VerdictKind.ESCALATE


@pytest.mark.asyncio
async def test_plan_gate_repair_count_ignores_non_plangate_bounces():
    # A validator-driven REPAIR(PLAN) also routes to the planner, but it must NOT
    # consume PlanGate's own repair budget.
    from_validator = Transition(from_node="validator", to_node="planner",
                                trigger=TriggerKind.GATE, reason="r", ts_iso="t")
    from_plangate = Transition(from_node="plan_gate", to_node="planner",
                               trigger=TriggerKind.GATE, reason="r", ts_iso="t")
    # 2 validator bounces + 1 plan_gate bounce → plan_gate count is 1 → still REPAIR
    state = SessionState(plan=Plan(), history=(from_validator, from_validator, from_plangate))
    res = await PlanGate().run(_ctx(state))
    assert res.verdict.kind is VerdictKind.REPAIR
