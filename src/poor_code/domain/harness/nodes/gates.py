# src/poor_code/domain/harness/nodes/gates.py
"""Gates — deterministic [C] nodes that emit a Verdict (never an output object).
The Verdict is what makes the graph *cycle*: route() turns repair(layer) into a
back-edge to that layer's shallowest producer (design.md §6/§16/§18)."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.session.models import (
    CodeContext, Layer, TriggerKind, Verdict, VerdictKind,
)


class UnderstandingGate:
    """Guards the understanding layer: a CodeContext with no candidates means the
    Locator found nothing groundable. Bounce back to it once (repair); if a prior
    gate bounce already happened and we still have nothing, escalate to the user."""

    name = "understanding_gate"

    async def run(self, ctx: NodeContext) -> NodeResult:
        cc = ctx.state.understanding or CodeContext()
        if cc.candidates:
            return NodeResult(output=None, verdict=Verdict(kind=VerdictKind.ADVANCE))
        if self._already_repaired(ctx.state):
            return NodeResult(output=None, verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query="No code candidates found even after re-locating.",
            ))
        return NodeResult(output=None, verdict=Verdict(
            kind=VerdictKind.REPAIR,
            layer=Layer.UNDERSTANDING,
            hint="Locator returned no candidates; widen the search.",
        ))

    @staticmethod
    def _already_repaired(state) -> bool:
        return any(
            t.trigger is TriggerKind.GATE and t.to_node == "locator"
            for t in state.history
        )
