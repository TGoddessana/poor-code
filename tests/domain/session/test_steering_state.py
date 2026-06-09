from poor_code.domain.session.models import (
    Cursor, Phase, Query, QueryKind, SessionState,
)


def test_with_steering_accumulates_immutably():
    s0 = SessionState()
    s1 = s0.with_steering("use auth.py pattern")
    s2 = s1.with_steering("write tests first")
    assert s0.steering_notes == ()                      # original untouched
    assert s1.steering_notes == ("use auth.py pattern",)
    assert s2.steering_notes == ("use auth.py pattern", "write tests first")


def test_without_pending_query_clears_only_that_field():
    q = Query(id="q1", kind=QueryKind.CLARIFY, prompt="?", options=())
    s = SessionState(pending_query=q, steering_notes=("keep me",))
    out = s.without_pending_query()
    assert out.pending_query is None
    assert out.steering_notes == ("keep me",)           # other fields preserved


def test_steering_notes_survive_serialization_round_trip(tmp_path):
    from poor_code.domain.session.store import (
        _session_state_to_dict, _dict_to_session_state,
    )
    s = SessionState(
        cursor=Cursor(phase=Phase.PLANNING, current_node="planner"),
        steering_notes=("a", "b"),
    )
    back = _dict_to_session_state(_session_state_to_dict(s), tmp_path)
    assert back.steering_notes == ("a", "b")
    assert back.cursor.current_node == "planner"
