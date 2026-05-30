from poor_code.domain.session.models import (
    SessionState, SessionStatus, Cursor, Phase, Request, RequestKind,
    CodeContext, CodeRef, TriggerKind,
)


def test_with_request_returns_new_state():
    s0 = SessionState()
    s1 = s0.with_request(Request(raw_text="x", kind=RequestKind.ENGINEERING))
    assert s0.request is None          # 원본 불변
    assert s1.request is not None and s1.request.raw_text == "x"


def test_with_understanding_returns_new_state():
    s0 = SessionState(cursor=Cursor(phase=Phase.LOCATING, current_node="locator"))
    cc = CodeContext(candidates=(CodeRef(file="a.py"),))
    s1 = s0.with_understanding(cc)
    assert s0.understanding is None
    assert s1.understanding.candidates[0].file == "a.py"


def test_advancing_to_moves_cursor_and_logs_history():
    s0 = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="router"))
    s1 = s0.advancing_to(
        node="locator", phase=Phase.LOCATING,
        trigger=TriggerKind.FORWARD, reason="engineering", ts_iso="2026-05-31T00:00:00+00:00",
    )
    assert s0.cursor.current_node == "router"          # 원본 불변
    assert s1.cursor.current_node == "locator"
    assert s1.cursor.phase is Phase.LOCATING
    assert len(s1.history) == 1
    assert s1.history[0].from_node == "router" and s1.history[0].to_node == "locator"
