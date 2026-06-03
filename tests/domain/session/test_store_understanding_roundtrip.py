from pathlib import Path

from poor_code.domain.session.models import (
    CodeContext, FileExcerpt, GroundingStatus, SessionState)
from poor_code.domain.session import store


def _roundtrip(state: SessionState) -> SessionState:
    # Use the same private (de)serializers the store relies on. Locate them by
    # name: the function that returns the dict containing an "understanding" key,
    # and its inverse that takes (dict, Path).
    to_dict = store._session_state_to_dict if hasattr(store, "_session_state_to_dict") else store._state_to_dict
    from_dict = store._dict_to_session_state
    return from_dict(to_dict(state), Path("."))


def test_understanding_roundtrip_preserves_briefing_and_grounding():
    state = SessionState(understanding=CodeContext(
        grounding=GroundingStatus.GREENFIELD,
        summary="needs an 800x600 ppm; validate via curl",
        excerpts=(FileExcerpt(path="orig.sh", text="ffmpeg scale=800:600", truncated=True),),
    ))
    cc = _roundtrip(state).understanding
    assert cc.grounding is GroundingStatus.GREENFIELD
    assert cc.summary == "needs an 800x600 ppm; validate via curl"
    assert cc.excerpts[0].path == "orig.sh"
    assert cc.excerpts[0].text == "ffmpeg scale=800:600"
    assert cc.excerpts[0].truncated is True


def test_understanding_roundtrip_back_compat_missing_keys():
    # Older persisted dicts won't have the new keys; deserialize must default them.
    from_dict = store._dict_to_session_state
    d = store._session_state_to_dict(SessionState()) if hasattr(store, "_session_state_to_dict") else store._state_to_dict(SessionState())
    # Build an "understanding" dict with ONLY the legacy keys:
    d["understanding"] = {"candidates": [], "confusers": [], "related_tests": [], "search_notes": "x"}
    cc = from_dict(d, Path(".")).understanding
    assert cc.search_notes == "x"
    assert cc.grounding is GroundingStatus.NOT_FOUND
    assert cc.summary == ""
    assert cc.excerpts == ()
