from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route, FORWARD
from poor_code.domain.session.models import (
    SessionState, Request, RequestKind, CodeContext,
    Verdict, VerdictKind, Layer,
)


def test_router_engineering_goes_to_locator():
    res = NodeResult(output=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    assert route("router", res, SessionState()) == "locator"


def test_router_lightweight_goes_to_fast_path():
    res = NodeResult(output=Request(raw_text="hi", kind=RequestKind.LIGHTWEIGHT))
    assert route("router", res, SessionState()) == "fast_path"


def test_locator_forwards_to_interviewer():
    res = NodeResult(output=CodeContext())
    assert route("locator", res, SessionState()) == "interviewer"


def test_repair_verdict_routes_to_shallowest_producer():
    res = NodeResult(output=None, verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN))
    assert route("completion_gate", res, SessionState()) == "planner"


def test_escalate_verdict_routes_to_user():
    res = NodeResult(output=None, verdict=Verdict(kind=VerdictKind.ESCALATE, query="?"))
    assert route("completion_gate", res, SessionState()) == "user"
