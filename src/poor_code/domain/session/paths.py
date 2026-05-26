"""Path computation for .poor-code/ layout. Internal — do not import outside this package."""
from __future__ import annotations

from pathlib import Path


def session_dir(root: Path, session_id: str) -> Path:
    return root / "sessions" / session_id


def session_json(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "session.json"


def session_state_json(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "state.json"


def task_dir(root: Path, session_id: str, task_id: str) -> Path:
    return session_dir(root, session_id) / "tasks" / task_id


def task_request_json(root: Path, session_id: str, task_id: str) -> Path:
    return task_dir(root, session_id, task_id) / "request.json"


def task_state_json(root: Path, session_id: str, task_id: str) -> Path:
    return task_dir(root, session_id, task_id) / "state.json"


def project_map_json(root: Path) -> Path:
    return root / "project_map.json"
