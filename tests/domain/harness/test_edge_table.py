from poor_code.domain.harness.graph import EdgeTable, ESCAPE
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import (
    SessionState, Verdict, VerdictKind, Layer, Request, RequestKind,
)


def _et():
    return EdgeTable(
        forward={("router", "engineering"): "explorer", ("planner", None): "plan_gate"},
        back_edges={Layer.PLAN: "planner"},
    )


def test_forward_edge_by_branch():
    r = NodeResult(output=Request(raw_text="x", kind=RequestKind.ENGINEERING), branch="engineering")
    assert _et().route("router", r, SessionState()) == "explorer"


def test_forward_edge_none_branch():
    r = NodeResult(output=None)
    assert _et().route("planner", r, SessionState()) == "plan_gate"


def test_back_edge_on_repair():
    r = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint="h"))
    assert _et().route("planner", r, SessionState()) == "planner"


def test_repair_unknown_layer_escapes():
    r = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION, hint="h"))
    assert _et().route("x", r, SessionState()) is ESCAPE


def test_escalate_routes_to_user():
    r = NodeResult(verdict=Verdict(kind=VerdictKind.ESCALATE, query="q"))
    assert _et().route("x", r, SessionState()) == "user"


def test_forward_miss_returns_none():
    r = NodeResult(output=None, branch="nope")
    assert _et().route("planner", r, SessionState()) is None
