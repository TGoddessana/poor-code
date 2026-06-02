# src/poor_code/domain/harness/driver.py
"""Driver — the dumb walker. Reads cursor → runs node → applies output (sole
writer) → asks route() for next → advances cursor → checkpoints. Smartness lives
in nodes/gates/route(), never here."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Callable

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import (
    CodeContext, Phase, Plan, Request, Requirement, SessionState, TriggerKind, Verdict, VerdictKind,
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

    async def run(self, state: SessionState, cancel: asyncio.Event) -> SessionState:
        while True:
            assert state.cursor is not None, "Driver requires a cursor"
            node = self._registry.get(state.cursor.current_node)
            if node is None:
                return state  # park: next node not implemented
            if cancel.is_set():
                return state

            result = await node.run(NodeContext(state=state, cancel=cancel))
            if result.query is not None:                   # suspend: await user
                state = state.with_pending_query(result.query)
                self._on_step(state)                       # checkpoint with pending query
                return state                               # cursor stays → re-entrant resume
            state = self._apply(state, result)            # ① write (sole writer)
            v = result.verdict
            if v is not None and v.kind is VerdictKind.REPAIR and v.hint:
                state = state.with_repair_hint(v.hint)     # carry hint to the re-entered node

            nxt = self._route(node.name, result, state)   # ② ask topology
            if nxt is None:
                return state                              # terminal STOP
            state = state.advancing_to(                   # ③ move cursor + log
                node=nxt,
                phase=_phase_for(nxt, state.cursor.phase),
                trigger=_trigger_for(result.verdict),
                reason=_reason_for(node.name, result),
                ts_iso=datetime.now(UTC).isoformat(),
            )
            self._on_step(state)                          # ④ checkpoint

    @staticmethod
    def _apply(state: SessionState, result: NodeResult) -> SessionState:
        out = result.output
        if isinstance(out, Request):
            return state.with_request(out)
        if isinstance(out, CodeContext):
            return state.with_understanding(out).with_repair_hint(None)
        if isinstance(out, Requirement):
            return state.with_requirement(out)
        if isinstance(out, Plan):
            return state.with_plan(out)
        return state


def _phase_for(node: str, current: Phase) -> Phase:
    return {
        "explorer": Phase.LOCATING,
        "locator": Phase.LOCATING,
        "interviewer": Phase.INTERVIEWING,
        "planner": Phase.PLANNING,
        "plan_gate": Phase.PLANNING,
    }.get(node, current)


def _trigger_for(verdict: Verdict | None) -> TriggerKind:
    return TriggerKind.GATE if verdict is not None else TriggerKind.FORWARD


def _reason_for(prev_node: str, result: NodeResult) -> str:
    if isinstance(result.output, Request):
        return result.output.kind.value
    return f"from {prev_node}"
