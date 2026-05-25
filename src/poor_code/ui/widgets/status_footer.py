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
        self.set_class(pct is not None and pct > 90, "danger")
        self.set_class(pct is not None and 70 < pct <= 90, "warn")

    @staticmethod
    def _format(state: AppState) -> str:
        u = state.usage
        ctx = StatusFooter._ctx_str(state)
        cost = f"${u.cost_usd:.4f}"
        model = state.model or ""
        return (
            f" ↑ {_k(u.input_tokens)}  ↓ {_k(u.output_tokens)}   "
            f"{cost}   {ctx}   {model}"
        )

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
