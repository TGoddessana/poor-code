# src/poor_code/domain/harness/nodes/gates.py
"""Gates — deterministic [C] nodes that emit a Verdict (never an output object).
The Verdict is what makes the graph *cycle*: route() turns repair(layer) into a
back-edge to that layer's shallowest producer (design.md §6/§16/§18)."""
from __future__ import annotations

from poor_code.domain.harness.grounding import validation_floor_hint
from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.session.models import (
    CodeContext, GroundingStatus, Layer, TriggerKind, Verdict, VerdictKind,
)


class UnderstandingGate:
    """Guards the understanding layer: a CodeContext with no candidates means the
    Locator found nothing groundable. Bounce back to it once (repair); if a prior
    gate bounce already happened and we still have nothing, escalate to the user."""

    name = "understanding_gate"

    async def run(self, ctx: NodeContext) -> NodeResult:
        cc = ctx.state.understanding or CodeContext()
        if cc.candidates or cc.grounding is GroundingStatus.GREENFIELD:
            return NodeResult(output=None, verdict=Verdict(kind=VerdictKind.ADVANCE))
        if self._already_repaired(ctx.state):
            return NodeResult(output=None, verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query="No code candidates found even after re-exploring.",
            ))
        hint = cc.search_notes.strip() or "Explorer found no candidates; widen the search."
        return NodeResult(output=None, verdict=Verdict(
            kind=VerdictKind.REPAIR,
            layer=Layer.UNDERSTANDING,
            hint=hint,
        ))

    @staticmethod
    def _already_repaired(state) -> bool:
        return any(
            t.trigger is TriggerKind.GATE and t.to_node == "explorer"
            for t in state.history
        )


class PlanGate:
    """Guards the planning layer: a Plan must have bounded tasks, edit scope,
    validation instructions, and an acyclic dependency graph."""

    name = "plan_gate"

    _MAX_EDITABLE = 3
    _REPAIR_BUDGET = 2

    async def run(self, ctx: NodeContext) -> NodeResult:
        hint = self._invalid_hint(ctx.state.plan)
        if hint is None:
            return NodeResult(output=None, verdict=Verdict(kind=VerdictKind.ADVANCE))
        if self._repair_count(ctx.state) >= self._REPAIR_BUDGET:
            return NodeResult(output=None, verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query=f"Plan is still invalid after replanning: {hint}",
            ))
        return NodeResult(output=None, verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint=hint))

    @classmethod
    def _invalid_hint(cls, plan) -> str | None:
        if plan is None or not plan.tasks:
            return "Plan has no tasks."

        ids = {task.id for task in plan.tasks}
        for task in plan.tasks:
            if not task.edit_scope.editable:
                return f"Task {task.id} has no editable paths."
            if len(task.edit_scope.editable) > cls._MAX_EDITABLE:
                return (f"Task {task.id} edits {len(task.edit_scope.editable)} files — "
                        "too broad; split into patch-sized tasks (<=3 files).")
            floor = validation_floor_hint(task.how_to_validate)
            if floor is not None:
                return f"Task {task.id} how_to_validate {floor}"

        for dep in plan.deps:
            if dep.task_id not in ids or dep.depends_on not in ids:
                return ("Plan has dependency referencing unknown task: "
                        f"{dep.task_id}->{dep.depends_on}.")

        if cls._has_cycle(ids, plan.deps):
            return "Plan dependency graph has a cycle."
        return None

    @staticmethod
    def _repair_count(state) -> int:
        return sum(1 for t in state.history
                   if t.trigger is TriggerKind.GATE
                   and t.from_node == "plan_gate"
                   and t.to_node == "planner")

    @staticmethod
    def _has_cycle(ids, deps) -> bool:
        graph = {task_id: [] for task_id in ids}
        for dep in deps:
            graph[dep.depends_on].append(dep.task_id)

        visiting = set()
        visited = set()

        def visit(node):
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for nxt in graph[node]:
                if visit(nxt):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in ids)


def _acceptance_repair_count(state) -> int:
    """Bounces back to acceptance_oracle from either the gate or the critic."""
    return sum(1 for t in state.history
               if t.trigger is TriggerKind.GATE and t.to_node == "acceptance_oracle")


class AcceptanceGate:
    """Deterministic floor on the AcceptanceSpec: it must have at least one check and
    each check must be a runnable command (not prose). Task-DEPENDENT adequacy is the
    acceptance_critic's job, NOT this gate's."""

    name = "acceptance_gate"

    _REPAIR_BUDGET = 2

    async def run(self, ctx: NodeContext) -> NodeResult:
        hint = self._invalid_hint(ctx.state.acceptance)
        if hint is None:
            return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
        if _acceptance_repair_count(ctx.state) >= self._REPAIR_BUDGET:
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query=f"Acceptance check still ill-formed after redesign: {hint}"))
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.ACCEPTANCE, hint=hint))

    @staticmethod
    def _invalid_hint(spec) -> str | None:
        if spec is None or not spec.checks:
            return "Acceptance spec has no checks; design at least one runnable check."
        for i, chk in enumerate(spec.checks, start=1):
            floor = validation_floor_hint(chk.command)
            if floor is not None:
                return f"Acceptance check {i} ({chk.criterion!r}) command {floor}"
        return None
