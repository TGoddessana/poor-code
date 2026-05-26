"""Bottom status bar — cumulative session usage + context-fill %.

Reactive on AppState. Color tier (normal/warn/danger) follows pi's
threshold: <70% / 70-90% / >90%.
"""
from __future__ import annotations

from textual.widgets import Static

from poor_code.ui.store import AppState


def _k(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class StatusFooter(Static):
    """Renders one line: ↑in ↓out $cost pct/ctx model."""

    def on_mount(self) -> None:
        self.add_class("status-footer")
        self.watch(self.app, "app_state", self._on_state_change)
        self._apply(self.app.app_state)

    def _on_state_change(self, state: AppState) -> None:
        self._apply(state)

    def _apply(self, state: AppState) -> None:
        self.update(self._format(state))
        pct = self._ctx_pct(state)
        ctx_danger = pct is not None and pct > 90
        ctx_warn = pct is not None and 70 < pct <= 90
        map_danger = state.project_map is not None and state.project_map.phase == "failed"
        map_warn = (
            state.project_map is not None
            and state.project_map.phase == "ready"
            and state.project_map.parse_error_count > 0
        )
        self.set_class(ctx_danger or map_danger, "danger")
        self.set_class((ctx_warn or map_warn) and not (ctx_danger or map_danger), "warn")

    @staticmethod
    def _format(state: AppState) -> str:
        u = state.usage
        ctx = StatusFooter._ctx_str(state)
        cost = f"${u.cost_usd:.4f}"
        model = state.model or ""
        base = (
            f" ↑ {_k(u.input_tokens)}  ↓ {_k(u.output_tokens)}   "
            f"{cost}   {ctx}   {model}"
        )
        suffix = StatusFooter._format_map(state)
        return base + suffix

    @staticmethod
    def _format_map(state: AppState) -> str:
        pm = state.project_map
        if pm is None:
            return ""
        if pm.phase == "indexing":
            return f"  · map: {pm.files_processed}/{pm.files_total}"
        if pm.phase == "ready":
            if pm.parse_error_count > 0:
                return f"  · map: {pm.files_total} files, {pm.parse_error_count} errors"
            return f"  · map: {pm.files_total} files"
        # failed
        return "  · map: failed"

    @staticmethod
    def _ctx_pct(state: AppState) -> float | None:
        meta = state.model_meta
        if meta is None or meta.context_size == 0:
            return None
        return state.last_turn_tokens / meta.context_size * 100

    @staticmethod
    def _ctx_str(state: AppState) -> str:
        pct = StatusFooter._ctx_pct(state)
        meta = state.model_meta
        if pct is None or meta is None:
            return "?/?"
        return f"{pct:.0f}%/{_k(meta.context_size)}"
