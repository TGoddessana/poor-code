from poor_code.domain.session.models import CodeContext, SessionState


def test_code_context_has_search_notes_default_empty():
    assert CodeContext().search_notes == ""
    assert CodeContext(search_notes="reconnect 0건").search_notes == "reconnect 0건"


def test_session_state_repair_hint_roundtrip():
    s = SessionState()
    assert s.repair_hint is None
    s2 = s.with_repair_hint("widen to stream/close")
    assert s2.repair_hint == "widen to stream/close"
    assert s.repair_hint is None  # frozen: original unchanged
    assert s2.with_repair_hint(None).repair_hint is None
