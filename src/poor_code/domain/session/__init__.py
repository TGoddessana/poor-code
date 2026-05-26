"""Public surface for the session domain.

Downstream code must import from this module only. `store`, `paths` are internal.
"""
from poor_code.domain.session.models import (
    Policies,
    Session,
    SessionState,
    SessionStatus,
    Task,
    TaskState,
    TaskStatus,
)
from poor_code.domain.session.service import SessionService

__all__ = [
    "Policies",
    "Session",
    "SessionService",
    "SessionState",
    "SessionStatus",
    "Task",
    "TaskState",
    "TaskStatus",
]

# Remove internal submodule references that leak into the package namespace
# when store.py does `from poor_code.domain.session import paths`.
import sys as _sys

_sys.modules[__name__].__dict__.pop("paths", None)
