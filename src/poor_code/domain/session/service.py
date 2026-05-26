"""Public façade for session/task lifecycle. The single import point for downstream sub-projects."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from poor_code.domain.session.models import (
    Policies,
    Session,
    SessionState,
    SessionStatus,
    Task,
    TaskState,
    TaskStatus,
)
from poor_code.domain.session.store import SessionStore


class SessionService:
    def __init__(self, store: SessionStore) -> None:
        self._store = store
        self._session: Session | None = None
        self._session_state: SessionState | None = None
        self._active_task: Task | None = None
        self._active_task_state: TaskState | None = None

    # ----- bootstrap -----

    def start_session(self, cwd: Path) -> Session:
        if self._session is not None:
            raise RuntimeError("session already started")

        s = Session(
            session_id=str(uuid.uuid4()),
            cwd=cwd,
            created_at=datetime.now(UTC),
        )
        self._store.write_session(s)
        self._store.write_session_state(s.session_id, SessionState())
        self._store.ensure_project_map()

        self._session = s
        self._session_state = SessionState()
        return s

    # ----- lifecycle -----

    def classify_message(self, text: str) -> Literal["new", "continuation"]:
        if self._session_state is None:
            raise RuntimeError("session not started")
        if self._session_state.active_task_id is None:
            return "new"
        assert self._active_task_state is not None
        if self._active_task_state.status in {TaskStatus.DONE, TaskStatus.ABORTED}:
            return "new"
        return "continuation"

    def begin_task(self, raw_request: str) -> Task:
        if self._session is None or self._session_state is None:
            raise RuntimeError("session not started")
        if self._session_state.active_task_id is not None:
            assert self._active_task_state is not None
            if self._active_task_state.status not in {TaskStatus.DONE, TaskStatus.ABORTED}:
                raise RuntimeError("active task already in progress")

        t = Task(
            task_id=str(uuid.uuid4()),
            session_id=self._session.session_id,
            raw_request=raw_request,
            created_at=datetime.now(UTC),
        )
        ts = TaskState()  # PENDING + locked policies

        self._store.write_task(t)
        self._store.write_task_state(self._session.session_id, t.task_id, ts)

        new_session_state = SessionState(status=SessionStatus.BUSY, active_task_id=t.task_id)
        self._store.write_session_state(self._session.session_id, new_session_state)

        self._active_task = t
        self._active_task_state = ts
        self._session_state = new_session_state
        return t

    def end_task(self, task_id: str, status: TaskStatus) -> None:
        if status not in {TaskStatus.DONE, TaskStatus.ABORTED}:
            raise ValueError("end_task requires terminal status (DONE or ABORTED)")
        if (
            self._session is None
            or self._session_state is None
            or self._session_state.active_task_id != task_id
            or self._active_task_state is None
        ):
            raise ValueError("task is not active")

        new_task_state = TaskState(
            status=status,
            policies=self._active_task_state.policies,
        )
        self._store.write_task_state(self._session.session_id, task_id, new_task_state)

        new_session_state = SessionState(status=SessionStatus.READY, active_task_id=None)
        self._store.write_session_state(self._session.session_id, new_session_state)

        self._active_task = None
        self._active_task_state = None
        self._session_state = new_session_state

    # ----- queries -----

    def active_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("session not started")
        return self._session

    def active_task(self) -> Task | None:
        return self._active_task

    def policies(self) -> Policies | None:
        if self._active_task_state is None:
            return None
        return self._active_task_state.policies

    def task_dir(self, task_id: str) -> Path:
        if self._session is None:
            raise RuntimeError("session not started")
        return self._store.task_dir(self._session.session_id, task_id)
