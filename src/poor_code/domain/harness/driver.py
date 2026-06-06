# src/poor_code/domain/harness/driver.py
"""Driver — the dumb walker. Reads cursor → runs node → applies the node's output
(via output.apply_to) → asks route() for next → advances cursor → checkpoints. The
Driver is the only place state is reassigned, but it holds no knowledge of output
types or topology — that lives in the outputs (apply_to), nodes/gates, and route()."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Callable

from poor_code.domain.harness.graph import ESCAPE, RouteResult
from poor_code.domain.harness.node import NodeContext, NodeResult, StructuredOutputError
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import (
    Request, SessionState, TriggerKind, Verdict, VerdictKind,
)
from poor_code.provider.client import LLMCallTimeout

# Recoverable INFERENCE failures: a weak model produced unusable output, or a call
# blew its wall-clock budget. These are expected at the tail of a low-param run and
# must NOT crash the process — the Driver turns them into a graceful ESCALATE so the
# session still produces a report. EVERY node validates LLM output through
# validate_output, which wraps bad output as StructuredOutputError — so a raw
# pydantic ValidationError reaching here is a PROGRAMMING bug, not LLM output, and is
# deliberately NOT caught (alongside KeyError, AssertionError, …); it must surface.
_RECOVERABLE_INFERENCE_ERRORS = (StructuredOutputError, LLMCallTimeout)

RouteFn = Callable[[str, NodeResult, SessionState], RouteResult]


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
            try:
                result = await node.run(NodeContext(state=state, cancel=cancel, sink=sink))
            except _RECOVERABLE_INFERENCE_ERRORS as exc:
                # A bad LLM call after the node's own re-roll budget is exhausted, or a
                # call that blew its time budget. Escalate gracefully instead of dying.
                result = NodeResult(verdict=Verdict(
                    kind=VerdictKind.ESCALATE,
                    query=f"{node.name} failed: {type(exc).__name__}: {str(exc)[:300]}"))
                if sink is not None and hasattr(sink, "node_repaired"):
                    sink.node_repaired(node.name, f"escalate: {type(exc).__name__}")
            if result.query is not None:                   # suspend: await user
                state = state.with_pending_query(result.query)
                self._on_step(state)                       # checkpoint with pending query
                return state                               # cursor stays → re-entrant resume
            state = self._apply(state, result)            # ① apply output (output.apply_to)
            v = result.verdict
            if v is not None and v.kind in (VerdictKind.REPAIR, VerdictKind.ESCALATE):
                detail = v.hint or v.query                 # REPAIR→hint, ESCALATE→query
                if detail and sink is not None and hasattr(sink, "node_repaired"):
                    layer = v.layer.value if v.layer is not None else "-"
                    sink.node_repaired(node.name, f"{v.kind.value}({layer}): {detail}")
            if v is not None and v.kind is VerdictKind.REPAIR and v.hint:
                state = state.with_repair_hint(v.hint)     # carry hint to the re-entered node

            nxt = self._route(node.name, result, state)   # ② ask topology
            # Two disjoint "can't resolve locally" outcomes both feed last_escape so a
            # wrapping CompiledGraph can bubble them: ESCALATE → route returned "user"
            # (fall through; top-level advances to "user" and parks), ESCAPE → unroutable
            # REPAIR (return now). last_escape is read only by CompiledGraph.run.
            if v is not None and v.kind is VerdictKind.ESCALATE:
                self.last_escape = v
            if nxt is ESCAPE:
                self.last_escape = v
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
