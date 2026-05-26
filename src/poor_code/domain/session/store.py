"""Disk I/O for session/task artifacts. Internal — do not import outside this package."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from poor_code.domain.session import paths
from poor_code.domain.session.models import (
    Policies,
    Session,
    SessionState,
    SessionStatus,
    Task,
    TaskState,
    TaskStatus,
)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: tmp file → os.replace.

    Guarantees that the original file at `path` (if any) is never partially overwritten:
    on any failure before os.replace, the original survives untouched. On failure of
    os.replace itself, the temporary file is cleaned up so it doesn't accumulate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"corrupt session file at {path}: {e}") from e


def _session_to_dict(s: Session) -> dict[str, Any]:
    return {
        "session_id": s.session_id,
        "cwd": str(s.cwd),
        "created_at": s.created_at.isoformat(),
        "parent_session_id": s.parent_session_id,
        "version": s.version,
    }


def _dict_to_session(d: dict[str, Any], src: Path) -> Session:
    try:
        return Session(
            session_id=d["session_id"],
            cwd=Path(d["cwd"]),
            created_at=datetime.fromisoformat(d["created_at"]),
            parent_session_id=d.get("parent_session_id"),
            version=d.get("version", 1),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"corrupt session file at {src}: {e}") from e


def _session_state_to_dict(st: SessionState) -> dict[str, Any]:
    return {"status": st.status.value, "active_task_id": st.active_task_id}


def _dict_to_session_state(d: dict[str, Any], src: Path) -> SessionState:
    try:
        return SessionState(
            status=SessionStatus(d["status"]),
            active_task_id=d.get("active_task_id"),
        )
    except (KeyError, ValueError) as e:
        raise ValueError(f"corrupt session file at {src}: {e}") from e


def _task_to_dict(t: Task) -> dict[str, Any]:
    return {
        "task_id": t.task_id,
        "session_id": t.session_id,
        "raw_request": t.raw_request,
        "created_at": t.created_at.isoformat(),
    }


def _dict_to_task(d: dict[str, Any], src: Path) -> Task:
    try:
        return Task(
            task_id=d["task_id"],
            session_id=d["session_id"],
            raw_request=d["raw_request"],
            created_at=datetime.fromisoformat(d["created_at"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"corrupt session file at {src}: {e}") from e


def _task_state_to_dict(ts: TaskState) -> dict[str, Any]:
    return {
        "status": ts.status.value,
        "policies": {"implementation_locked": ts.policies.implementation_locked},
    }


def _dict_to_task_state(d: dict[str, Any], src: Path) -> TaskState:
    try:
        return TaskState(
            status=TaskStatus(d["status"]),
            policies=Policies(implementation_locked=d["policies"]["implementation_locked"]),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise ValueError(f"corrupt session file at {src}: {e}") from e


class SessionStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def write_session(self, s: Session) -> None:
        _atomic_write_json(paths.session_json(self._root, s.session_id), _session_to_dict(s))

    def read_session(self, session_id: str) -> Session:
        path = paths.session_json(self._root, session_id)
        return _dict_to_session(_read_json(path), path)

    def write_session_state(self, session_id: str, st: SessionState) -> None:
        _atomic_write_json(
            paths.session_state_json(self._root, session_id),
            _session_state_to_dict(st),
        )

    def read_session_state(self, session_id: str) -> SessionState:
        path = paths.session_state_json(self._root, session_id)
        return _dict_to_session_state(_read_json(path), path)

    def write_task(self, t: Task) -> None:
        _atomic_write_json(
            paths.task_request_json(self._root, t.session_id, t.task_id),
            _task_to_dict(t),
        )

    def read_task(self, session_id: str, task_id: str) -> Task:
        path = paths.task_request_json(self._root, session_id, task_id)
        return _dict_to_task(_read_json(path), path)

    def write_task_state(self, session_id: str, task_id: str, st: TaskState) -> None:
        _atomic_write_json(
            paths.task_state_json(self._root, session_id, task_id),
            _task_state_to_dict(st),
        )

    def read_task_state(self, session_id: str, task_id: str) -> TaskState:
        path = paths.task_state_json(self._root, session_id, task_id)
        return _dict_to_task_state(_read_json(path), path)

    def ensure_project_map(self) -> None:
        path = paths.project_map_json(self._root)
        if path.exists():
            return
        _atomic_write_json(path, {"status": "uninitialized", "version": 1})

    def task_dir(self, session_id: str, task_id: str) -> Path:
        return paths.task_dir(self._root, session_id, task_id)
