from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route, FORWARD
from poor_code.domain.session.models import SessionState


def test_noderesult_has_branch_default_none():
    assert NodeResult().branch is None


def test_route_uses_explicit_branch(monkeypatch):
    monkeypatch.setitem(FORWARD, ("zzz_test_node", "left"), "target_left")
    r = NodeResult(branch="left")
    assert route("zzz_test_node", r, SessionState()) == "target_left"
