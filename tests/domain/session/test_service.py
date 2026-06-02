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
    assert data["status"] == "ready" and data["active_task_id"] is None


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


def test_classify_returns_new_when_no_active_task(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    assert service.classify_message("hi") == "new"


def test_classify_takes_text_but_ignores_it(service: SessionService, tmp_path: Path):
    """Signature reserves space for future LLM-based classifier; V1 must not branch on text."""
    service.start_session(tmp_path / "cwd")
    assert service.classify_message("") == "new"
    assert service.classify_message("totally unrelated topic") == "new"


def test_begin_task_creates_request_and_state(service: SessionService, root: Path, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("refactor auth")

    assert t.task_id
    assert t.raw_request == "refactor auth"
    assert (root / "sessions" / service.active_session().session_id / "tasks" / t.task_id / "request.json").exists()
    assert (root / "sessions" / service.active_session().session_id / "tasks" / t.task_id / "state.json").exists()


def test_begin_task_sets_session_state_busy(service: SessionService, root: Path, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("refactor auth")

    sid = service.active_session().session_id
    data = json.loads((root / "sessions" / sid / "state.json").read_text(encoding="utf-8"))
    assert data["status"] == "busy" and data["active_task_id"] == t.task_id


def test_begin_task_writes_pending_state_with_locked_policies(service: SessionService, root: Path, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("refactor auth")

    sid = service.active_session().session_id
    data = json.loads((root / "sessions" / sid / "tasks" / t.task_id / "state.json").read_text(encoding="utf-8"))
    assert data == {"status": "pending", "policies": {"implementation_locked": True}}


def test_begin_task_after_classify_returns_continuation(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    service.begin_task("first task")
    assert service.classify_message("more details") == "continuation"


def test_begin_task_while_active_raises(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    service.begin_task("first task")
    with pytest.raises(RuntimeError, match="active task already in progress"):
        service.begin_task("second task")


def test_begin_task_before_start_raises(service: SessionService):
    with pytest.raises(RuntimeError, match="not started"):
        service.begin_task("oops")


def test_active_task_is_none_before_begin(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    assert service.active_task() is None


def test_active_task_returns_task_after_begin(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("x")
    assert service.active_task() == t


from poor_code.domain.session.models import WorkItemStatus


def test_end_task_done_transitions_session_state(service: SessionService, root: Path, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("x")
    service.end_task(t.task_id, WorkItemStatus.DONE)

    sid = service.active_session().session_id
    data = json.loads((root / "sessions" / sid / "state.json").read_text(encoding="utf-8"))
    assert data["status"] == "ready" and data["active_task_id"] is None

    task_data = json.loads((root / "sessions" / sid / "tasks" / t.task_id / "state.json").read_text(encoding="utf-8"))
    assert task_data["status"] == "done"


def test_end_task_aborted_transitions_session_state(service: SessionService, root: Path, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("x")
    service.end_task(t.task_id, WorkItemStatus.ABORTED)

    sid = service.active_session().session_id
    task_data = json.loads((root / "sessions" / sid / "tasks" / t.task_id / "state.json").read_text(encoding="utf-8"))
    assert task_data["status"] == "aborted"


def test_classify_after_end_done_returns_new(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("x")
    service.end_task(t.task_id, WorkItemStatus.DONE)
    assert service.classify_message("next") == "new"


def test_classify_after_end_aborted_returns_new(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("x")
    service.end_task(t.task_id, WorkItemStatus.ABORTED)
    assert service.classify_message("next") == "new"


def test_end_task_with_pending_status_raises(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("x")
    with pytest.raises(ValueError, match="terminal status"):
        service.end_task(t.task_id, WorkItemStatus.PENDING)


def test_end_task_with_wrong_id_raises(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    service.begin_task("x")
    with pytest.raises(ValueError, match="not active"):
        service.end_task("bogus-tid", WorkItemStatus.DONE)


def test_begin_after_end_starts_new_task(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t1 = service.begin_task("first")
    service.end_task(t1.task_id, WorkItemStatus.DONE)

    t2 = service.begin_task("second")
    assert t2.task_id != t1.task_id
    assert service.active_task() == t2


def test_policies_none_before_begin(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    assert service.policies() is None


def test_policies_locked_after_begin(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    service.begin_task("x")
    p = service.policies()
    assert p is not None
    assert p.implementation_locked is True


def test_policies_none_after_end(service: SessionService, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("x")
    service.end_task(t.task_id, WorkItemStatus.DONE)
    assert service.policies() is None


def test_service_task_dir_returns_disk_path(service: SessionService, root: Path, tmp_path: Path):
    service.start_session(tmp_path / "cwd")
    t = service.begin_task("x")
    sid = service.active_session().session_id
    assert service.task_dir(t.task_id) == root / "sessions" / sid / "tasks" / t.task_id


def test_service_task_dir_works_for_non_active_task_id(service: SessionService, root: Path, tmp_path: Path):
    """task_dir is pure path computation — does not validate existence."""
    service.start_session(tmp_path / "cwd")
    sid = service.active_session().session_id
    assert service.task_dir("never-existed") == root / "sessions" / sid / "tasks" / "never-existed"
