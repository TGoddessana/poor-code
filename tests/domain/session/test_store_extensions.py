from dataclasses import dataclass
from pathlib import Path

import pytest

from poor_code.domain.session.models import SessionState, SessionStatus
from poor_code.domain.session.artifacts import register_artifact
from poor_code.domain.session.store import (
    _session_state_to_dict, _dict_to_session_state,
)


@dataclass(frozen=True)
class _Widget:
    n: int

    def to_json_dict(self) -> dict:
        return {"n": self.n}

    @classmethod
    def from_json_dict(cls, d: dict) -> "_Widget":
        return cls(n=d["n"])


def test_empty_data_produces_no_extensions_key():
    out = _session_state_to_dict(SessionState())
    assert "extensions" not in out


def test_old_file_without_extensions_loads_clean():
    out = _session_state_to_dict(SessionState())
    assert "extensions" not in out
    back = _dict_to_session_state(out, Path("dummy"))
    assert back._data == {}
    assert back.status is SessionStatus.READY


def test_roundtrip_with_registered_artifact():
    register_artifact("store_ext_widget", _Widget)
    st = SessionState().put(_Widget(3))
    out = _session_state_to_dict(st)
    assert out["extensions"] == {"store_ext_widget": {"n": 3}}
    back = _dict_to_session_state(out, Path("dummy"))
    assert back.require(_Widget) == _Widget(3)


def test_unknown_artifact_name_skipped_core_intact(recwarn):
    out = _session_state_to_dict(SessionState())
    out["extensions"] = {"mystery_plugin": {"whatever": 1}}
    back = _dict_to_session_state(out, Path("dummy"))
    assert back._data == {}
    assert back.status is SessionStatus.READY
    assert any("mystery_plugin" in str(w.message) for w in recwarn.list)
