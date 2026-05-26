"""Domain models for session/task lifecycle. See CONTRACT.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class SessionStatus(str, Enum):
    READY = "ready"
    BUSY = "busy"
    CLOSED = "closed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    ABORTED = "aborted"
    # S2~S9 add their phase values (MAPPING, INTERVIEWING, ...) when introducing those cycles.


@dataclass(frozen=True, slots=True)
class Policies:
    implementation_locked: bool = True


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    cwd: Path
    created_at: datetime
    parent_session_id: str | None = None
    version: int = 1


@dataclass(frozen=True, slots=True)
class SessionState:
    status: SessionStatus = SessionStatus.READY
    active_task_id: str | None = None


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    session_id: str
    raw_request: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TaskState:
    status: TaskStatus = TaskStatus.PENDING
    policies: Policies = field(default_factory=Policies)
