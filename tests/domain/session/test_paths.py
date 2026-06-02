from pathlib import Path

from poor_code.domain.session import paths


def test_session_dir(tmp_path: Path):
    assert paths.session_dir(tmp_path, "sid1") == tmp_path / "sessions" / "sid1"


def test_session_json(tmp_path: Path):
    assert paths.session_json(tmp_path, "sid1") == tmp_path / "sessions" / "sid1" / "session.json"


def test_session_state_json(tmp_path: Path):
    assert paths.session_state_json(tmp_path, "sid1") == tmp_path / "sessions" / "sid1" / "state.json"


def test_task_dir(tmp_path: Path):
    assert paths.work_item_dir(tmp_path, "sid1", "tid1") == tmp_path / "sessions" / "sid1" / "tasks" / "tid1"


def test_work_item_request_json(tmp_path: Path):
    assert paths.work_item_request_json(tmp_path, "sid1", "tid1") == tmp_path / "sessions" / "sid1" / "tasks" / "tid1" / "request.json"


def test_work_item_state_json(tmp_path: Path):
    assert paths.work_item_state_json(tmp_path, "sid1", "tid1") == tmp_path / "sessions" / "sid1" / "tasks" / "tid1" / "state.json"


def test_project_map_json(tmp_path: Path):
    assert paths.project_map_json(tmp_path) == tmp_path / "project_map.json"
