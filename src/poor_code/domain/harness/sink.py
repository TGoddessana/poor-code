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
    NodeContextCaptured,
    NodeEntered,
    NodeFinished,
    NodeProduced,
    NodeRawOutput,
    NodeThinkingDelta,
    PlanReady,
    QueryRaised,
    ReportReady,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    TurnConcluded,
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


def _query_prompt(query: Query) -> str:
    lines: list[str] = []
    if query.context:
        lines.append(f"Context: {query.context}")
    lines.append(query.prompt)
    if query.rationale:
        lines.append(f"Why: {query.rationale}")
    if query.resolves:
        lines.append(f"Resolves: {query.resolves}")
    return "\n".join(lines)


class TurnSink:
    def __init__(self, turn_id: str, dispatch: Callable[[Event], None],
                 narrator: object | None = None, trace: object | None = None) -> None:
        self._turn_id = turn_id
        self._dispatch = dispatch
        self._narrator = narrator
        self._trace = trace
        self._thinking_chars: dict[str, int] = {}

    def _record(self, **fields) -> None:
        if self._trace is not None:
            self._trace.write(fields)

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
        self._record(type="node_entered", node=node, phase=phase, activity=act or "")

    def node_produced(self, node: str, phase: str, *, result: object | None = None,
                      headline: str = "", detail: tuple[str, ...] = ()) -> None:
        head, det = headline, detail
        if not head and self._narrator is not None and result is not None:
            head, det = self._narrator.summary(node, result)
        if not head:
            return
        self._dispatch(NodeProduced(turn_id=self._turn_id, node=node, phase=phase,
                                    headline=head, detail=tuple(det)))
        self._record(type="node_produced", node=node, phase=phase, headline=head,
                     detail=list(det))

    def node_repaired(self, node: str, detail: str) -> None:
        # The TUI surfaces repairs through existing node/phase events; this records
        # the repair to the durable trace for post-mortem.
        self._record(type="node_repaired", node=node, detail=detail)

    def node_context(self, node: str, phase: str, messages: list) -> None:
        full = "\n\n".join(
            f"[{m.get('role', '?')}]\n{m.get('content', '')}" for m in messages)
        n = len(messages)
        summary = f"{n} msg{'s' if n != 1 else ''} · ~{len(full) / 1024:.1f} KB"
        self._dispatch(NodeContextCaptured(
            turn_id=self._turn_id, node=node, summary=summary, full=full))
        self._record(type="node_context", node=node, summary=summary, full=full)

    def node_thinking_delta(self, node: str, text: str) -> None:
        if not text:
            return
        self._thinking_chars[node] = self._thinking_chars.get(node, 0) + len(text)
        self._dispatch(NodeThinkingDelta(turn_id=self._turn_id, node=node, text=text))

    def node_raw_output(self, node: str, raw: str) -> None:
        self._dispatch(NodeRawOutput(turn_id=self._turn_id, node=node, raw=raw))
        self._record(type="node_raw_output", node=node, raw=raw)

    def node_finished(self, node: str, phase: str, duration_sec: float, status: str) -> None:
        self._dispatch(NodeFinished(
            turn_id=self._turn_id, node=node, phase=phase,
            duration_sec=duration_sec, status=status))
        self._record(type="node_finished", node=node, phase=phase,
                     duration_sec=duration_sec, status=status,
                     thinking_chars=self._thinking_chars.pop(node, 0))

    def turn_concluded(self, reason: str, detail: str = "") -> None:
        self._dispatch(TurnConcluded(turn_id=self._turn_id, reason=reason, detail=detail))
        self._record(type="turn_concluded", reason=reason, detail=detail)

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
            prompt=_query_prompt(query), options=tuple(query.options)))

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
