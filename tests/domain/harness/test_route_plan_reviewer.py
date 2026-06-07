from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    Layer, SessionState, Verdict, VerdictKind,
)


def test_plan_gate_advance_forwards_to_plan_reviewer():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("plan_gate", res, SessionState()) == "plan_reviewer"


def test_plan_reviewer_advance_forwards_to_plan_confirm_gate():
    # plan_reviewer now routes through plan_confirm_gate before provisioner
    res = NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("plan_reviewer", res, SessionState()) == "plan_confirm_gate"


def test_provisioner_advance_forwards_to_implement_loop():
    # the task-execution loop is now folded into the implement_loop subgraph; provisioner
    # forwards into it (task_selector is the subgraph's INTERNAL entry, not on the outer edge).
    res = NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("provisioner", res, SessionState()) == "implement_loop"


def test_plan_reviewer_repair_loops_back_to_planner():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN))
    assert route("plan_reviewer", res, SessionState()) == "planner"
