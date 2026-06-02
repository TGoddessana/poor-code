from poor_code.domain.session.store import _session_state_to_dict, _dict_to_session_state
from poor_code.domain.session.models import SessionState, CodeContext, CodeRef
from pathlib import Path


def test_roundtrip_preserves_search_notes_and_repair_hint():
    state = SessionState(
        understanding=CodeContext(
            candidates=(CodeRef(file="a.py", symbol="f"),),
            search_notes="reconnect 0건; stream 미탐색",
        ),
        repair_hint="widen to stream/close",
    )
    d = _session_state_to_dict(state)
    back = _dict_to_session_state(d, Path("x.json"))
    assert back.understanding.search_notes == "reconnect 0건; stream 미탐색"
    assert back.repair_hint == "widen to stream/close"


def test_roundtrip_defaults_when_absent():
    # old files without the new keys must still load
    d = _session_state_to_dict(SessionState(understanding=CodeContext()))
    d.pop("repair_hint", None)
    d["understanding"].pop("search_notes", None)
    back = _dict_to_session_state(d, Path("x.json"))
    assert back.repair_hint is None
    assert back.understanding.search_notes == ""
