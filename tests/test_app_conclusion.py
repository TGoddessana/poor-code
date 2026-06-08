from poor_code.app import classify_conclusion
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Query, QueryKind,
)


def _state(node="composer", **kw):
    return SessionState(cursor=Cursor(phase=Phase.IMPLEMENTING, current_node=node), **kw)


class _FakeReport:
    outcome = type("O", (), {"value": "succeeded"})()


def test_cancelled():
    assert classify_conclusion(_state(), cancelled=True)[0] == "cancelled"


def test_error():
    r, d = classify_conclusion(_state(), error="ValueError: boom")
    assert r == "error" and "boom" in d


def test_suspended_on_pending_query():
    st = _state(pending_query=Query(id="q", kind=QueryKind.CLARIFY, prompt="why?"))
    r, d = classify_conclusion(st)
    assert r == "suspended" and "why?" in d


def test_completed_on_report():
    st = _state()
    object.__setattr__(st, "report", _FakeReport())
    r, _ = classify_conclusion(st)
    assert r == "completed"


def test_parked_on_unimplemented_node():
    r, d = classify_conclusion(_state(node="composer"))
    assert r == "parked" and "composer" in d
