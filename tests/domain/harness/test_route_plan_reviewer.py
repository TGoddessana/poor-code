from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    Layer, SessionState, Verdict, VerdictKind,
)


def test_plan_gate_advance_forwards_to_plan_reviewer():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("plan_gate", res, SessionState()) == "plan_reviewer"


def test_plan_reviewer_advance_forwards_to_task_selector():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("plan_reviewer", res, SessionState()) == "task_selector"


def test_plan_reviewer_repair_loops_back_to_planner():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN))
    assert route("plan_reviewer", res, SessionState()) == "planner"
