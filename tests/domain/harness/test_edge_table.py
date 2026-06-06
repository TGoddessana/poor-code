from poor_code.domain.harness.graph import EdgeTable, ESCAPE, Rewrite
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import (
    SessionState, Verdict, VerdictKind, Layer, Request, RequestKind, Policy,
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


def _et_with_rewrite():
    # remap interviewer -> acceptance_oracle only under FULL_AUTO (mirrors real skip)
    skip = Rewrite(when=lambda s: s.policy is Policy.FULL_AUTO,
                   remap={"interviewer": "acceptance_oracle"})
    return EdgeTable(
        forward={("acceptance_oracle", None): "interviewer"},
        back_edges={},
        rewrites=(skip,),
    )


def test_rewrite_applied_when_condition_true():
    r = NodeResult(output=None)
    st = SessionState(policy=Policy.FULL_AUTO)
    assert _et_with_rewrite().route("acceptance_oracle", r, st) == "acceptance_oracle"


def test_rewrite_skipped_when_condition_false():
    r = NodeResult(output=None)
    st = SessionState(policy=Policy.SUPERVISED)
    assert _et_with_rewrite().route("acceptance_oracle", r, st) == "interviewer"


def test_rewrite_passthrough_for_unmapped_node():
    # a next node not in remap is returned unchanged even when condition is true
    skip = Rewrite(when=lambda s: True, remap={"interviewer": "x"})
    et = EdgeTable(forward={("planner", None): "plan_gate"}, back_edges={}, rewrites=(skip,))
    r = NodeResult(output=None)
    assert et.route("planner", r, SessionState()) == "plan_gate"
