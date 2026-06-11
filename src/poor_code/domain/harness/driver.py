# src/poor_code/domain/harness/driver.py
"""Driver — the dumb walker. Reads cursor → runs node → applies the node's output
(via output.apply_to) → asks route() for next → advances cursor → checkpoints. The
Driver is the only place state is reassigned, but it holds no knowledge of output
types or topology — that lives in the outputs (apply_to), nodes/gates, and route()."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from poor_code.domain.harness.graph import ESCAPE, RouteResult
from poor_code.domain.harness.node import NodeContext, NodeResult, StructuredOutputError
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.smart_driver import AdviceRequest, DriverAdvisor
from poor_code.domain.session.models import (
    DriverDecisionRecord,
    Layer,
    NodeFeedbackPacket,
    Query,
    QueryKind,
    Request,
    SessionState,
    TriggerKind,
    Verdict,
    VerdictKind,
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


@dataclass
class DriverRuntime:
    on_step: Callable[[SessionState], None] = field(default_factory=lambda: (lambda _s: None))
    advisor: DriverAdvisor | None = None
    smart_enabled: bool = False
    cwd: object | None = None


class Driver:
    def __init__(
        self,
        registry: NodeRegistry,
        route: RouteFn,
        on_step: Callable[[SessionState], None] | None = None,
        *,
        runtime: DriverRuntime | None = None,
        graph_name: str = "root",
    ) -> None:
        self._registry = registry
        self._route = route
        self._runtime = runtime or DriverRuntime()
        if on_step is not None:
            self._runtime.on_step = on_step
        self._on_step = self._runtime.on_step
        self._graph_name = graph_name
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

            state, smart_flow = await self._maybe_handle_smart_utterance(
                state, node.name, cancel, sink)
            if smart_flow == "return":
                return state
            if smart_flow == "restart_loop":
                continue

            if sink is not None:
                sink.node_entered(node.name, state.cursor.phase.value, state=state)
            _t0 = time.monotonic()
            _status = "done"
            try:
                result = await node.run(NodeContext(
                    state=state, cancel=cancel, sink=sink, runtime=self._runtime))
            except _RECOVERABLE_INFERENCE_ERRORS as exc:
                # A bad LLM call after the node's own re-roll budget is exhausted, or a
                # call that blew its time budget. Escalate gracefully instead of dying.
                _status = "failed"
                result = NodeResult(verdict=Verdict(
                    kind=VerdictKind.ESCALATE,
                    query=f"{node.name} failed: {type(exc).__name__}: {str(exc)[:300]}"))
                if sink is not None and hasattr(sink, "node_repaired"):
                    sink.node_repaired(node.name, f"escalate: {type(exc).__name__}")
            if result.query is not None and _status == "done":
                _status = "parked"
            if sink is not None and hasattr(sink, "node_finished"):
                sink.node_finished(
                    node.name, state.cursor.phase.value, time.monotonic() - _t0, _status)
            state = state.consuming_feedback_for(node.name)
            if result.query is not None:                   # suspend: await user
                state = state.with_pending_query(result.query)
                self._on_step(state)                       # checkpoint with pending query
                return state                               # cursor stays → re-entrant resume
            state = self._apply(state, result)            # ① apply output (output.apply_to)
            if (
                sink is not None
                and (result.output is not None or result.verdict is not None)
                and hasattr(sink, "node_produced")
            ):
                sink.node_produced(node.name, state.cursor.phase.value, result=result)
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
            state = self._advance(state, node, nxt, result)  # ③ move cursor + log
            self._on_step(state)                          # ④ checkpoint

    @staticmethod
    def _apply(state: SessionState, result: NodeResult) -> SessionState:
        out = result.output
        if out is None:
            return state
        return out.apply_to(state)

    async def _maybe_handle_smart_utterance(
        self, state: SessionState, node_name: str, cancel: asyncio.Event,
        sink: object | None,
    ) -> tuple[SessionState, str]:
        if cancel.is_set() or not self._runtime.smart_enabled or self._runtime.advisor is None:
            return state, "proceed"
        seen = state.driver_control.processed_steering_count
        total = len(state.steering_notes)
        if total <= seen:
            return state, "proceed"
        try:
            decision = await self._runtime.advisor.advise(AdviceRequest(
                state=state,
                graph_name=self._graph_name,
                current_node=node_name,
                available_nodes=(
                    self._registry.names() if hasattr(self._registry, "names")
                    else (node_name,)
                ),
                cwd=self._runtime.cwd,  # type: ignore[arg-type]
            ))
        except Exception:
            # Advisor failure must never derail the deterministic graph.
            return (
                _without_interrupted_query(state).with_processed_steering_count(total),
                "proceed",
            )

        state = state.with_processed_steering_count(total)
        state = state.adding_feedback_packets(decision.feedback_packets)
        state = state.with_driver_decision(DriverDecisionRecord(
            action=decision.action,
            target_node=decision.target_node,
            layer=decision.layer,
            reason=decision.reason,
            message=decision.user_message,
            instruction=_instruction_summary(decision.feedback_packets),
        ))
        self._emit_driver_intervention(state, decision, sink)

        action = decision.action
        if action in {"answer_only", "ask_user", "rollback_request"}:
            prompt = decision.ask_prompt or decision.user_message or decision.reason
            if action == "answer_only" and "이어" not in prompt:
                prompt = f"{prompt}\n\n이어갈까요?"
            state = state.with_pending_query(Query(
                id=f"smart-driver-{total}",
                kind=QueryKind.CONFIRM,
                prompt=prompt or "이어갈까요?",
                options=("Continue", "Give more direction"),
                resolves="smart_driver_hitl",
                rationale=decision.reason,
            ))
            self._on_step(state)
            return state, "return"

        state = _without_interrupted_query(state)
        if action in {"answer_and_continue", "continue_default", "restart_current"}:
            return state, "proceed"

        if action in {"redirect", "redirect_and_inject", "pivot_request"}:
            target = decision.target_node or ("router" if action == "pivot_request" else None)
            redirected = self._redirect(state, node_name, target, decision.reason)
            if redirected is state:
                return state, "proceed"
            self._on_step(redirected)
            return redirected, "restart_loop"

        if action == "bubble_repair":
            repaired, flow = self._bubble_repair(state, node_name, decision.layer, decision.reason)
            self._on_step(repaired)
            return repaired, flow

        return state, "proceed"

    def _redirect(
        self, state: SessionState, node_name: str, target: str | None, reason: str
    ) -> SessionState:
        if not target or target == state.cursor.current_node:
            return state
        if self._registry.get(target) is None:
            return state
        current = self._registry.get(node_name)
        target_node = self._registry.get(target)
        phase = (
            getattr(target_node, "phase", None)
            or getattr(current, "phase", None)
            or state.cursor.phase
        )
        return state.advancing_to(
            node=target,
            phase=phase,
            trigger=TriggerKind.USER,
            reason=f"smart_driver: {reason or 'redirect'}",
            ts_iso=datetime.now(UTC).isoformat(),
        )

    def _bubble_repair(
        self, state: SessionState, node_name: str, layer_name: str | None, reason: str
    ) -> tuple[SessionState, str]:
        layer = _layer_for(layer_name)
        if layer is None:
            return state, "proceed"
        verdict = Verdict(kind=VerdictKind.REPAIR, layer=layer, hint=reason)
        state = state.with_repair_hint(reason or None)
        nxt = self._route(node_name, NodeResult(verdict=verdict), state)
        if nxt is ESCAPE:
            self.last_escape = verdict
            return state, "return"
        if nxt is None:
            return state, "return"
        current = self._registry.get(node_name)
        target = self._registry.get(nxt)
        phase = getattr(target, "phase", None) or getattr(current, "phase", None) or state.cursor.phase
        state = state.advancing_to(
            node=nxt,
            phase=phase,
            trigger=TriggerKind.USER,
            reason=f"smart_driver repair: {reason or layer.value}",
            ts_iso=datetime.now(UTC).isoformat(),
        )
        return state, "restart_loop"

    def _advance(self, state: SessionState, node, nxt: str, result: NodeResult) -> SessionState:
        nxt_node = self._registry.get(nxt)
        # phase priority: next node's attr → current node's attr (park edge, nxt unregistered)
        # → cursor phase (phaseless nodes e.g. router/fast_path)
        nxt_phase = getattr(nxt_node, "phase", None) or getattr(node, "phase", None) or state.cursor.phase
        return state.advancing_to(
            node=nxt,
            phase=nxt_phase,
            trigger=_trigger_for(result.verdict),
            reason=_reason_for(node.name, result),
            ts_iso=datetime.now(UTC).isoformat(),
        )

    def _emit_driver_intervention(self, state, decision, sink: object | None) -> None:
        if sink is None:
            return
        phase = state.cursor.phase.value if state.cursor is not None else "routing"
        if hasattr(sink, "node_entered"):
            sink.node_entered("driver", phase, state=state, activity="Driver intervention")
        detail = tuple(_intervention_detail(decision))
        headline = decision.user_message or decision.reason or f"Smart Driver: {decision.action}"
        if hasattr(sink, "node_produced"):
            sink.node_produced(
                "driver", phase, headline=headline, detail=detail)
        if hasattr(sink, "node_finished"):
            sink.node_finished("driver", phase, 0.0, "done")


def _trigger_for(verdict: Verdict | None) -> TriggerKind:
    return TriggerKind.GATE if verdict is not None else TriggerKind.FORWARD


def _reason_for(prev_node: str, result: NodeResult) -> str:
    if isinstance(result.output, Request):
        return result.output.kind.value
    return f"from {prev_node}"


def _layer_for(name: str | None) -> Layer | None:
    if not name:
        return None
    try:
        return Layer(name)
    except ValueError:
        return None


def _instruction_summary(packets: tuple[NodeFeedbackPacket, ...]) -> str:
    return "\n".join(p.instruction for p in packets if p.instruction)


def _without_interrupted_query(state: SessionState) -> SessionState:
    query = state.pending_query
    if query is None or query.resolves == "smart_driver_hitl":
        return state
    return state.without_pending_query()


def _intervention_detail(decision) -> list[str]:
    detail = [f"Action: {decision.action}"]
    if decision.target_node:
        detail.append(f"Target: {decision.target_node}")
    if decision.layer:
        detail.append(f"Layer: {decision.layer}")
    for packet in decision.feedback_packets:
        if packet.instruction:
            detail.append(f"Instruction: {packet.instruction}")
        for item in packet.evidence[:3]:
            detail.append(f"Evidence: {item}")
    return detail
