"""Path computation for .poor-code/ layout. Internal — do not import outside this package."""
from __future__ import annotations

from pathlib import Path


def session_dir(root: Path, session_id: str) -> Path:
    return root / "sessions" / session_id


def session_json(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "session.json"


def session_state_json(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "state.json"


def work_item_dir(root: Path, session_id: str, task_id: str) -> Path:
    return session_dir(root, session_id) / "tasks" / task_id


def work_item_request_json(root: Path, session_id: str, task_id: str) -> Path:
    return work_item_dir(root, session_id, task_id) / "request.json"


def work_item_state_json(root: Path, session_id: str, task_id: str) -> Path:
    return work_item_dir(root, session_id, task_id) / "state.json"


def changeset_json(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "changeset.json"


def attempt_dir(root: Path, session_id: str, task_id: str, attempt_id: str) -> Path:
    return work_item_dir(root, session_id, task_id) / "attempts" / attempt_id


def project_map_json(root: Path) -> Path:
    return root / "project_map.json"


def turn_dir(root: Path, session_id: str, turn_id: str) -> Path:
    return session_dir(root, session_id) / "turns" / turn_id


def turn_trace_jsonl(root: Path, session_id: str, turn_id: str) -> Path:
    return turn_dir(root, session_id, turn_id) / "trace.jsonl"
