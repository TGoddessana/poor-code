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


# =========================================================================
# Events — domain → UI
# =========================================================================


@dataclass(frozen=True)
class Event:
    """Marker base. Concrete events subclass this."""


# --- Turn lifecycle ---


@dataclass(frozen=True)
class TurnStarted(Event):
    cmd_id: str
    turn_id: str = field(default_factory=_new_id)


@dataclass(frozen=True)
class TurnEnded(Event):
    turn_id: str
    duration_sec: float
    model: str


@dataclass(frozen=True)
class TurnFailed(Event):
    turn_id: str
    error: str


# --- Streaming output ---


@dataclass(frozen=True)
class AssistantTextDelta(Event):
    """One chunk of streaming text. Reducer accumulates per turn."""
    turn_id: str
    text: str


@dataclass(frozen=True)
class AssistantMessageCompleted(Event):
    turn_id: str
    text: str


# --- Tool calls ---


@dataclass(frozen=True)
class ToolCallStarted(Event):
    turn_id: str
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolCallFinished(Event):
    turn_id: str
    tool_call_id: str
    result: Any


@dataclass(frozen=True)
class ToolCallFailed(Event):
    turn_id: str
    tool_call_id: str
    error: str


# --- Telemetry ---


@dataclass(frozen=True)
class UsageUpdated(Event):
    turn_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


# --- Project Map build (S2) ---


@dataclass(frozen=True)
class ProjectMapBuildStarted(Event):
    files_total: int


@dataclass(frozen=True)
class ProjectMapBuildProgress(Event):
    files_processed: int
    files_total: int


@dataclass(frozen=True)
class ProjectMapBuildFinished(Event):
    files_total: int
    parse_error_count: int
    duration_ms: int


@dataclass(frozen=True)
class ProjectMapBuildFailed(Event):
    error: str


# --- Harness graph (S3 TUI wiring) ---


@dataclass(frozen=True)
class NodeEntered(Event):
    """Driver entered a graph node. UI uses this to label the segments that follow."""
    turn_id: str
    node: str
    phase: str
    activity: str = ""   # human-readable present-tense narration; "" → UI falls back


@dataclass(frozen=True)
class QueryRaised(Event):
    """Graph suspended awaiting user input. Primitives only (no domain Query object)."""
    turn_id: str
    query_id: str
    kind: str
    prompt: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanReady(Event):
    """Graph parked with a completed plan, pre-rendered to display lines."""
    turn_id: str
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportReady(Event):
    """Graph reached its terminal Report, pre-rendered for display."""
    turn_id: str
    outcome: str
    summary: str
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeProduced(Event):
    """A node finished and produced data. Carries a one-line headline + optional
    detail lines for an inline 'result card'. Strings are supplied by whoever
    drives (static narrator today, LLM-driver later) — UI just renders them."""
    turn_id: str
    node: str
    phase: str
    headline: str
    detail: tuple[str, ...] = ()
