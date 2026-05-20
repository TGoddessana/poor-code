"""Contract between UI and domain.

UI dispatches Commands, domain emits Events. Both are immutable dataclasses.
This module depends only on the standard library and is importable from
anywhere in the package. See docs/superpowers/specs/2026-05-20-ui-app-architecture-design.md.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


def _new_id() -> str:
    return uuid.uuid4().hex


# =========================================================================
# Commands — UI → domain
# =========================================================================


@dataclass(frozen=True)
class Command:
    """Marker base. Concrete commands subclass this."""


@dataclass(frozen=True)
class SendPrompt(Command):
    text: str
    cmd_id: str = field(default_factory=_new_id)


@dataclass(frozen=True)
class CancelTurn(Command):
    cmd_id: str = field(default_factory=_new_id)


@dataclass(frozen=True)
class RunSlashCommand(Command):
    name: str
    args: tuple[str, ...] = ()
    cmd_id: str = field(default_factory=_new_id)
