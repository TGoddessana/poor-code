import asyncio

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.gates import PlanGate, UnderstandingGate
from poor_code.domain.session.models import (
    CodeContext, CodeRef, Dependency, EditScope, GroundingStatus, Layer, Plan,
    SessionState, Task, Transition, TriggerKind, VerdictKind,
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
    }
    data.update(overrides)
    return Task(**data)


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
    res = await PlanGate().run(_ctx(SessionState(plan=Plan(), history=(prior,))))
    assert res.verdict.kind is VerdictKind.ESCALATE


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
