import json
from pathlib import Path

import pytest

from poor_code.domain.session.models import SessionStatus
from poor_code.domain.session.service import SessionService
from poor_code.domain.session.store import SessionStore


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Simulated <cwd>/.poor-code/ root."""
    return tmp_path / "cwd" / ".poor-code"


@pytest.fixture
def service(root: Path) -> SessionService:
    return SessionService(SessionStore(root))


def test_start_session_creates_all_artifacts(service: SessionService, root: Path, tmp_path: Path):
    cwd = tmp_path / "cwd"
    s = service.start_session(cwd)

    assert s.session_id  # truthy uuid
    assert s.cwd == cwd

    # Disk artifacts.
    assert (root / "sessions" / s.session_id / "session.json").exists()
    assert (root / "sessions" / s.session_id / "state.json").exists()
    assert (root / "project_map.json").exists()


def test_start_session_writes_default_session_state(service: SessionService, root: Path, tmp_path: Path):
    cwd = tmp_path / "cwd"
    s = service.start_session(cwd)
    state_file = root / "sessions" / s.session_id / "state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data == {"status": "ready", "active_task_id": None}


def test_start_session_does_not_overwrite_existing_project_map(service: SessionService, root: Path, tmp_path: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "project_map.json").write_text('{"status": "ready"}', encoding="utf-8")

    cwd = tmp_path / "cwd"
    service.start_session(cwd)

    data = json.loads((root / "project_map.json").read_text(encoding="utf-8"))
    assert data == {"status": "ready"}


def test_start_session_called_twice_raises(service: SessionService, tmp_path: Path):
    cwd = tmp_path / "cwd"
    service.start_session(cwd)
    with pytest.raises(RuntimeError, match="already started"):
        service.start_session(cwd)


def test_active_session_before_start_raises(service: SessionService):
    with pytest.raises(RuntimeError, match="not started"):
        service.active_session()


def test_active_session_after_start_returns_session(service: SessionService, tmp_path: Path):
    cwd = tmp_path / "cwd"
    s = service.start_session(cwd)
    assert service.active_session() == s
