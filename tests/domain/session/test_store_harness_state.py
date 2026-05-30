import uuid
from pathlib import Path
from poor_code.domain.session.store import SessionStore
from poor_code.domain.session.models import (
    SessionState, SessionStatus, Cursor, Phase, Request, RequestKind,
    CodeContext, CodeRef, Transition, TriggerKind,
)


def test_session_state_roundtrip_with_harness_fields(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = uuid.uuid4().hex
    st = SessionState(
        status=SessionStatus.BUSY,
        cursor=Cursor(phase=Phase.LOCATING, current_node="locator"),
        request=Request(raw_text="fix login", kind=RequestKind.ENGINEERING),
        understanding=CodeContext(candidates=(CodeRef(file="a.py", symbol="x", lineno=3),)),
        history=(Transition(from_node="router", to_node="locator",
                            trigger=TriggerKind.FORWARD, reason="engineering",
                            ts_iso="2026-05-31T00:00:00+00:00"),),
    )
    store.write_session_state(sid, st)
    got = store.read_session_state(sid)

    assert got.status is SessionStatus.BUSY
    assert got.cursor.current_node == "locator" and got.cursor.phase is Phase.LOCATING
    assert got.request.kind is RequestKind.ENGINEERING
    assert got.understanding.candidates[0].symbol == "x"
    assert got.history[0].to_node == "locator"


def test_empty_session_state_roundtrip(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = uuid.uuid4().hex
    store.write_session_state(sid, SessionState())
    got = store.read_session_state(sid)
    assert got.cursor is None and got.request is None and got.history == ()
