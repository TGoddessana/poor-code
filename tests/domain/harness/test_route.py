from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route, FORWARD
from poor_code.domain.session.models import (
    SessionState, Request, RequestKind, CodeContext,
    Verdict, VerdictKind, Layer,
)


def test_router_engineering_goes_to_explorer():
    res = NodeResult(output=Request(raw_text="x", kind=RequestKind.ENGINEERING),
                     branch="engineering")
    assert route("router", res, SessionState()) == "explorer"


def test_router_lightweight_goes_to_fast_path():
    res = NodeResult(output=Request(raw_text="hi", kind=RequestKind.LIGHTWEIGHT),
                     branch="lightweight")
    assert route("router", res, SessionState()) == "fast_path"


def test_explorer_forwards_to_understanding_gate():
    res = NodeResult(output=CodeContext())
    assert route("explorer", res, SessionState()) == "understanding_gate"


def test_understanding_gate_advance_forwards_to_interviewer():
    res = NodeResult(output=None, verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("understanding_gate", res, SessionState()) == "interviewer"


def test_understanding_gate_repair_loops_back_to_explorer():
    res = NodeResult(output=None, verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.UNDERSTANDING))
    assert route("understanding_gate", res, SessionState()) == "explorer"


def test_repair_verdict_routes_to_shallowest_producer():
    res = NodeResult(output=None, verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN))
    assert route("completion_gate", res, SessionState()) == "planner"


def test_escalate_verdict_routes_to_user():
    res = NodeResult(output=None, verdict=Verdict(kind=VerdictKind.ESCALATE, query="?"))
    assert route("completion_gate", res, SessionState()) == "user"


def test_router_branch_is_carried_on_result_not_inferred():
    # route() no longer inspects Request: branch must come from NodeResult.branch
    from poor_code.domain.harness.route import route
    from poor_code.domain.harness.node import NodeResult
    from poor_code.domain.session.models import SessionState, Request, RequestKind
    r_no_branch = NodeResult(output=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    assert route("router", r_no_branch, SessionState()) is None  # no branch → forward miss
    r_branch = NodeResult(
        output=Request(raw_text="x", kind=RequestKind.ENGINEERING), branch="engineering")
    assert route("router", r_branch, SessionState()) == "explorer"


def test_interviewer_forwards_to_acceptance_oracle():
    # acceptance_oracle now sits between interviewer and planner
    from poor_code.domain.harness.route import route
    from poor_code.domain.harness.node import NodeResult
    from poor_code.domain.session.models import Requirement, SessionState
    res = NodeResult(output=Requirement(summary="done"))
    nxt = route("interviewer", res, SessionState())
    assert nxt == "acceptance_oracle"
