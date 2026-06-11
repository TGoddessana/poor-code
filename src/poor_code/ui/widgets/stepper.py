"""StepperBar — fixed top rail showing the 6 coarse pipeline phases with the
current one highlighted. Driven purely by AppState.current_phase / phases_seen,
tolerant of unknown / revisited phases (so a future dynamic LLM driver can't
break it)."""
from __future__ import annotations

from textual.widgets import Static

from poor_code.ui.store import AppState, NodeLabelSegment

_RAIL = [
    ("routing", "Route"),
    ("locating", "Locate"),
    ("interviewing", "Clarify"),
    ("planning", "Plan"),
    ("implementing", "Build"),
    ("finalizing", "Done"),
]


def render_stepper(state: AppState) -> str:
    if state.current_phase is None and not state.phases_seen:
        return ""
    parts = []
    for key, label in _RAIL:
        if key == state.current_phase:
            parts.append(f"⟳ {label}")
        elif key in state.phases_seen:
            parts.append(f"✓ {label}")
        else:
            parts.append(f"· {label}")
    detail = _current_detail(state)
    if detail:
        parts.append(f"│ {detail}")
    return "   ".join(parts)


def _current_detail(state: AppState) -> str:
    if not state.turns:
        return ""
    for seg in reversed(state.turns[-1].segments):
        if isinstance(seg, NodeLabelSegment):
            label = seg.activity or seg.node
            if seg.activity and seg.node not in seg.activity:
                label = f"{label} · {seg.node}"
            return label
    return ""


class StepperBar(Static):
    """Reactive on app_state; renders the phase rail (hidden when empty)."""

    def on_mount(self) -> None:
        self.add_class("stepper-bar")
        self.watch(self.app, "app_state", self._apply)
        self._apply(self.app.app_state)

    def _apply(self, state: AppState) -> None:
        line = render_stepper(state)
        self.update(line)
        self.display = bool(line)
