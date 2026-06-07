# src/poor_code/domain/harness/sink.py
"""TurnSink — the per-turn bridge from domain nodes to the UI event stream.

Nodes/Driver call these methods during a run; each builds a messages.py Event
stamped with this turn's id and dispatches it. Lives in domain/ but imports only
messages.py (the shared contract) and session models — never ui/."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from poor_code.domain.session.models import Plan, Query
from poor_code.messages import (
    AssistantTextDelta,
    Event,
    NodeEntered,
    NodeProduced,
    PlanReady,
    QueryRaised,
    ReportReady,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnded,
    TurnFailed,
    TurnStarted,
)


def _plan_lines(plan: Plan) -> tuple[str, ...]:
    lines: list[str] = []
    for i, t in enumerate(plan.tasks, start=1):
        edits = ", ".join(t.edit_scope.editable) or "(none)"
        validate = t.how_to_validate or "(none)"
        lines.append(f"{i}. {t.title} — edits: {edits} — validate: {validate}")
    return tuple(lines)


def _report_lines(report) -> tuple[str, ...]:
    return tuple(f"{t.title} — {t.status.value}" for t in report.tasks)


class TurnSink:
    def __init__(self, turn_id: str, dispatch: Callable[[Event], None],
                 narrator: object | None = None) -> None:
        self._turn_id = turn_id
        self._dispatch = dispatch
        self._narrator = narrator

    # --- node-facing (called mid-run via NodeContext.sink) ---
    def node_entered(self, node: str, phase: str, *, state: object | None = None,
                     activity: str = "") -> None:
        act = activity
        if not act and self._narrator is not None and state is not None:
            phase_arg = phase
            cursor = getattr(state, "cursor", None)
            if cursor is not None and getattr(cursor, "phase", None) is not None:
                phase_arg = cursor.phase
            act = self._narrator.activity(node, phase_arg, state)
        self._dispatch(NodeEntered(turn_id=self._turn_id, node=node, phase=phase, activity=act or ""))

    def node_produced(self, node: str, phase: str, *, result: object | None = None,
                      headline: str = "", detail: tuple[str, ...] = ()) -> None:
        head, det = headline, detail
        if not head and self._narrator is not None and result is not None:
            head, det = self._narrator.summary(node, result)
        if not head:
            return
        self._dispatch(NodeProduced(turn_id=self._turn_id, node=node, phase=phase,
                                    headline=head, detail=tuple(det)))

    def node_repaired(self, node: str, detail: str) -> None:
        # Observability hook used by headless (StderrSink). The TUI surfaces repairs
        # through existing node/phase events, so this is a no-op here — adding a new
        # message event would require touching the hardwired messages.py reducer.
        pass

    def text_delta(self, text: str) -> None:
        if text:
            self._dispatch(AssistantTextDelta(turn_id=self._turn_id, text=text))

    def tool_started(self, tool_call_id: str, tool_name: str, args: dict[str, Any]) -> None:
        self._dispatch(ToolCallStarted(
            turn_id=self._turn_id, tool_call_id=tool_call_id,
            tool_name=tool_name, args=args))

    def tool_finished(self, tool_call_id: str, result: Any) -> None:
        self._dispatch(ToolCallFinished(
            turn_id=self._turn_id, tool_call_id=tool_call_id, result=result))

    def tool_failed(self, tool_call_id: str, error: str) -> None:
        self._dispatch(ToolCallFailed(
            turn_id=self._turn_id, tool_call_id=tool_call_id, error=error))

    # --- app-facing (called after Driver returns) ---
    def query_raised(self, query: Query) -> None:
        self._dispatch(QueryRaised(
            turn_id=self._turn_id, query_id=query.id, kind=query.kind.value,
            prompt=query.prompt, options=tuple(query.options)))

    def plan_ready(self, plan: Plan) -> None:
        self._dispatch(PlanReady(turn_id=self._turn_id, lines=_plan_lines(plan)))

    def report_ready(self, report) -> None:
        self._dispatch(ReportReady(
            turn_id=self._turn_id, outcome=report.outcome.value,
            summary=report.summary, lines=_report_lines(report)))

    # --- fast_path bridge: forward Agent's events under this turn ---
    def forward(self, event: Event) -> None:
        if isinstance(event, (TurnStarted, TurnEnded, TurnFailed)):
            return
        self._dispatch(replace(event, turn_id=self._turn_id))
