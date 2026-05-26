from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from poor_code.domain.session.models import (
    Session,
    SessionState,
    SessionStatus,
)
from poor_code.domain.session.store import SessionStore, _atomic_write_json


def test_atomic_write_creates_file(tmp_path: Path):
    target = tmp_path / "sub" / "out.json"
    _atomic_write_json(target, {"k": "v"})
    assert target.exists()
    assert '"k": "v"' in target.read_text(encoding="utf-8")


def test_atomic_write_overwrites_existing(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")
    _atomic_write_json(target, {"new": True})
    assert "new" in target.read_text(encoding="utf-8")
    assert "old" not in target.read_text(encoding="utf-8")


def test_atomic_write_failure_preserves_original(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text('{"original": true}', encoding="utf-8")

    with patch("os.replace", side_effect=OSError("simulated disk error")):
        with pytest.raises(OSError, match="simulated"):
            _atomic_write_json(target, {"new": True})

    # Original survives.
    assert "original" in target.read_text(encoding="utf-8")
    assert "new" not in target.read_text(encoding="utf-8")


def test_atomic_write_no_tmp_file_left_on_success(tmp_path: Path):
    target = tmp_path / "out.json"
    _atomic_write_json(target, {"k": "v"})
    assert target.exists()
    # No .tmp sibling.
    assert not (tmp_path / "out.json.tmp").exists()


def test_atomic_write_failure_cleans_up_tmp_file(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text('{"original": true}', encoding="utf-8")

    with patch("os.replace", side_effect=OSError("simulated")):
        with pytest.raises(OSError):
            _atomic_write_json(target, {"new": True})

    # Stale .tmp should not remain.
    assert not (tmp_path / "out.json.tmp").exists()
    # Original still intact.
    assert "original" in target.read_text(encoding="utf-8")


def test_session_round_trip(tmp_path: Path):
    store = SessionStore(tmp_path)
    s = Session(
        session_id="sid1",
        cwd=Path("/some/cwd"),
        created_at=datetime(2026, 5, 26, 12, 0, tzinfo=UTC),
    )
    store.write_session(s)
    loaded = store.read_session("sid1")
    assert loaded == s


def test_session_state_round_trip_with_defaults(tmp_path: Path):
    store = SessionStore(tmp_path)
    st = SessionState()
    store.write_session_state("sid1", st)
    loaded = store.read_session_state("sid1")
    assert loaded == st


def test_session_state_round_trip_with_active_task(tmp_path: Path):
    store = SessionStore(tmp_path)
    st = SessionState(status=SessionStatus.BUSY, active_task_id="tid1")
    store.write_session_state("sid1", st)
    loaded = store.read_session_state("sid1")
    assert loaded == st


def test_read_session_missing_raises_filenotfound(tmp_path: Path):
    store = SessionStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.read_session("nonexistent")


def test_read_session_malformed_raises_value_error_with_path(tmp_path: Path):
    store = SessionStore(tmp_path)
    s = Session(
        session_id="sid1",
        cwd=Path("/cwd"),
        created_at=datetime(2026, 5, 26, tzinfo=UTC),
    )
    store.write_session(s)
    # Corrupt the file.
    from poor_code.domain.session import paths
    paths.session_json(tmp_path, "sid1").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        store.read_session("sid1")


from poor_code.domain.session.models import (
    Policies,
    Task,
    TaskState,
    TaskStatus,
)


def test_task_round_trip(tmp_path: Path):
    store = SessionStore(tmp_path)
    t = Task(
        task_id="tid1",
        session_id="sid1",
        raw_request="refactor auth",
        created_at=datetime(2026, 5, 26, 12, 0, tzinfo=UTC),
    )
    store.write_task(t)
    loaded = store.read_task("sid1", "tid1")
    assert loaded == t


def test_task_state_round_trip_with_defaults(tmp_path: Path):
    store = SessionStore(tmp_path)
    ts = TaskState()
    store.write_task_state("sid1", "tid1", ts)
    loaded = store.read_task_state("sid1", "tid1")
    assert loaded == ts
    assert loaded.policies.implementation_locked is True
    assert loaded.status is TaskStatus.PENDING


def test_task_state_with_done_status_round_trip(tmp_path: Path):
    store = SessionStore(tmp_path)
    ts = TaskState(status=TaskStatus.DONE, policies=Policies(implementation_locked=False))
    store.write_task_state("sid1", "tid1", ts)
    loaded = store.read_task_state("sid1", "tid1")
    assert loaded == ts
