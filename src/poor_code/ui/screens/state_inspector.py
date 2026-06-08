"""StateInspector — a modal snapshot of the agent's data flow.

Two sources, both read-only:
  • AppState — the UI's own view (request, phase, progress, produced cards, plan).
  • the parked live SessionState (app._harness_state) when present — the actual
    CONTEXT the nodes were fed (code context, interview Q&A, requirement). This is
    available whenever the turn is suspended on a question or finished, which is
    exactly when "what context went in?" is the question being asked.
Opened by ctrl+i or /state, closed by escape."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from poor_code.ui.store import (
    AppState, NodeResultSegment, PlanSegment, ReportSegment,
)


def render_inspector(state: AppState) -> str:
    if not state.turns:
        return "No active work yet."
    turn = state.turns[-1]
    lines = [
        f"Request:   {turn.user_text}",
        f"Phase:     {state.current_phase or '-'}",
        f"Progress:  {', '.join(state.phases_seen) or '-'}",
    ]
    results = [s for s in turn.segments if isinstance(s, NodeResultSegment)]
    if results:
        lines.append("Produced:")
        for r in results[-6:]:
            lines.append(f"  • {r.node}: {r.headline}")
    plans = [s for s in turn.segments if isinstance(s, PlanSegment)]
    if plans:
        n = len(plans[-1].lines)
        lines.append(f"Plan:      {n} {'task' if n == 1 else 'tasks'}")
    reports = [s for s in turn.segments if isinstance(s, ReportSegment)]
    if reports:
        lines.append(f"Report:    {reports[-1].outcome} — {reports[-1].summary}")
    return "\n".join(lines)


def _ref(r) -> str:
    where = r.file if r.symbol is None else f"{r.file}::{r.symbol}"
    return f"{where}:{r.lineno}" if r.lineno else where


def pick_context_source(app):
    """Live in-flight SessionState (set each driver step) wins over the parked
    state (set only after the driver returns), so the inspector shows context
    mid-turn, not just when suspended/finished."""
    return getattr(app, "_live_state", None) or getattr(app, "_harness_state", None)


def render_context(session) -> str:
    """The live context fed to the nodes, from the parked SessionState. Empty when
    there's no parked state (mid-turn, before the first suspend)."""
    if session is None:
        return ""
    lines: list[str] = []

    cc = getattr(session, "understanding", None)
    if cc is not None:
        grounding = getattr(getattr(cc, "grounding", None), "value", None)
        head = "CODE CONTEXT"
        if grounding:
            head += f"  ({grounding})"
        lines.append(head)
        if cc.summary:
            lines.append(f"  summary: {cc.summary}")
        for label, refs in (("candidates", cc.candidates),
                            ("confusers", cc.confusers),
                            ("related_tests", cc.related_tests)):
            if refs:
                lines.append(f"  {label}:")
                lines.extend(f"    - {_ref(r)}" for r in refs)
        if cc.excerpts:
            shown = [e.path + (" (truncated)" if getattr(e, "truncated", False) else "")
                     for e in cc.excerpts]
            lines.append(f"  excerpts: {', '.join(shown)}")

    interview = getattr(session, "interview", ())
    if interview:
        lines.append("INTERVIEW")
        for aq in interview:
            ans = aq.response.answer
            if getattr(aq.response, "chosen_option", None):
                ans = f"[{aq.response.chosen_option}] {ans}"
            lines.append(f"  Q: {aq.query.prompt}")
            lines.append(f"    → {ans}")

    pq = getattr(session, "pending_query", None)
    if pq is not None:
        lines.append("PENDING QUESTION")
        lines.append(f"  {pq.prompt}")
        if pq.options:
            lines.extend(f"    [{i}] {o}" for i, o in enumerate(pq.options, 1))

    req = getattr(session, "requirement", None)
    if req is not None:
        lines.append("REQUIREMENT")
        lines.append(f"  {req.summary}")
        for label, items in (("acceptance", req.acceptance),
                            ("out_of_scope", req.out_of_scope),
                            ("assumptions", req.assumptions),
                            ("open_questions", req.open_questions)):
            if items:
                lines.append(f"  {label}:")
                lines.extend(f"    - {it}" for it in items)

    return "\n".join(lines)


class StateInspector(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("ctrl+i", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Container(id="inspector-box"):
            yield Static("Agent state  ·  ctrl+i / esc to close", classes="inspector-title")
            with VerticalScroll(id="inspector-scroll"):
                yield Static(render_inspector(self.app.app_state), id="inspector-body")
                context = render_context(pick_context_source(self.app))
                ctx = Static(context, id="inspector-context")
                ctx.display = bool(context)
                yield ctx
