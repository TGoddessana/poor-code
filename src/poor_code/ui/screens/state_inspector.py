"""StateInspector — a modal snapshot of the agent's data flow, derived purely
from AppState (never touches domain live state). Opened by ctrl+i or /state,
closed by escape."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
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


class StateInspector(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("ctrl+i", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Container(id="inspector-box"):
            yield Static("Agent state  ·  ctrl+i / esc to close", classes="inspector-title")
            yield Static(render_inspector(self.app.app_state), id="inspector-body")
