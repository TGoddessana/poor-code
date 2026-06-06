# src/poor_code/domain/harness/driver.py
"""Driver — the dumb walker. Reads cursor → runs node → applies output (sole
writer) → asks route() for next → advances cursor → checkpoints. Smartness lives
in nodes/gates/route(), never here."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Callable

from poor_code.domain.harness.graph import ESCAPE
from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import (
    Request, SessionState, TriggerKind, Verdict, VerdictKind,
)

RouteFn = Callable[[str, NodeResult, SessionState], "str | None"]


class Driver:
    def __init__(
        self,
        registry: NodeRegistry,
        route: RouteFn,
        on_step: Callable[[SessionState], None] | None = None,
    ) -> None:
        self._registry = registry
        self._route = route
        self._on_step = on_step or (lambda _s: None)
        self.last_escape: Verdict | None = None

    async def run(
        self, state: SessionState, cancel: asyncio.Event, *, sink: object | None = None
    ) -> SessionState:
        self.last_escape = None
        while True:
            assert state.cursor is not None, "Driver requires a cursor"
            node = self._registry.get(state.cursor.current_node)
            if node is None:
                return state  # park: next node not implemented
            if cancel.is_set():
                return state

            if sink is not None:
                sink.node_entered(node.name, state.cursor.phase.value)
            result = await node.run(NodeContext(state=state, cancel=cancel, sink=sink))
            if result.query is not None:                   # suspend: await user
                state = state.with_pending_query(result.query)
                self._on_step(state)                       # checkpoint with pending query
                return state                               # cursor stays → re-entrant resume
            state = self._apply(state, result)            # ① write (sole writer)
            v = result.verdict
            if v is not None and v.kind in (VerdictKind.REPAIR, VerdictKind.ESCALATE):
                detail = v.hint or v.query                 # REPAIR→hint, ESCALATE→query
                if detail and sink is not None and hasattr(sink, "node_repaired"):
                    layer = v.layer.value if v.layer is not None else "-"
                    sink.node_repaired(node.name, f"{v.kind.value}({layer}): {detail}")
            if v is not None and v.kind is VerdictKind.REPAIR and v.hint:
                state = state.with_repair_hint(v.hint)     # carry hint to the re-entered node

            nxt = self._route(node.name, result, state)   # ② ask topology
            if nxt is ESCAPE:
                self.last_escape = result.verdict          # unresolved here → bubble to outer graph
                return state
            if nxt is None:
                return state                              # terminal STOP
            nxt_node = self._registry.get(nxt)
            # phase priority: next node's attr → current node's attr (park edge, nxt unregistered)
            # → cursor phase (phaseless nodes e.g. router/fast_path)
            nxt_phase = getattr(nxt_node, "phase", None) or getattr(node, "phase", None) or state.cursor.phase
            state = state.advancing_to(                   # ③ move cursor + log
                node=nxt,
                phase=nxt_phase,
                trigger=_trigger_for(result.verdict),
                reason=_reason_for(node.name, result),
                ts_iso=datetime.now(UTC).isoformat(),
            )
            self._on_step(state)                          # ④ checkpoint

    @staticmethod
    def _apply(state: SessionState, result: NodeResult) -> SessionState:
        out = result.output
        if out is None:
            return state
        return out.apply_to(state)


def _trigger_for(verdict: Verdict | None) -> TriggerKind:
    return TriggerKind.GATE if verdict is not None else TriggerKind.FORWARD


def _reason_for(prev_node: str, result: NodeResult) -> str:
    if isinstance(result.output, Request):
        return result.output.kind.value
    return f"from {prev_node}"
