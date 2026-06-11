# src/poor_code/domain/harness/nodes/gates.py
"""Gates — deterministic [C] nodes that emit a Verdict (never an output object).
The Verdict is what makes the graph *cycle*: route() turns repair(layer) into a
back-edge to that layer's shallowest producer (design.md §6/§16/§18)."""
from __future__ import annotations

from poor_code.domain.harness.grounding import validation_floor_hint
from poor_code.domain.harness.ledger import has_section
from poor_code.domain.harness.node import GateNode
from poor_code.domain.session.models import (
    CodeContext, GroundingStatus, Layer, Phase, TriggerKind,
)


class UnderstandingGate(GateNode):
    """Guards the understanding layer: a CodeContext with no candidates means the
    Locator found nothing groundable. Bounce back to it once (repair); if a prior
    gate bounce already happened and we still have nothing, escalate to the user."""

    name = "understanding_gate"
    layer = Layer.UNDERSTANDING
    repair_budget = 1
    phase = Phase.LOCATING

    def check(self, state) -> str | None:
        cc = state.understanding or CodeContext()
        if cc.candidates or cc.grounding is GroundingStatus.GREENFIELD:
            return None
        return cc.search_notes.strip() or "Explorer found no candidates; widen the search."

    def escalate_query(self, hint: str) -> str:
        return "No code candidates found even after re-exploring."


class PlanGate(GateNode):
    """Guards the planning layer: a Plan must have bounded tasks with editable scope
    (<=3 files each), a plan_md section per skeleton task, and an acyclic dependency
    graph."""

    name = "plan_gate"
    layer = Layer.PLAN
    repair_budget = 2
    phase = Phase.PLANNING

    _MAX_EDITABLE = 3

    def check(self, state) -> str | None:
        return self._invalid_hint(state.plan)

    def escalate_query(self, hint: str) -> str:
        return f"Plan is still invalid after replanning: {hint}"

    def _repair_count(self, state) -> int:
        # Preserve original counting: GATE bounces specifically plan_gate -> planner.
        return sum(1 for t in state.history
                   if t.trigger is TriggerKind.GATE
                   and t.from_node == "plan_gate"
                   and t.to_node == "planner")

    @classmethod
    def _invalid_hint(cls, plan) -> str | None:
        if plan is None or not plan.tasks:
            return "Plan has no tasks."
        ids = {task.id for task in plan.tasks}
        md = plan.plan_md or ""
        if not md.strip():
            return ("Plan has no plan_md narrative; every task needs a "
                    "'## <task id>:' section describing what to build.")
        for task in plan.tasks:
            if not task.edit_scope.editable:
                return f"Task {task.id} has no editable paths."
            if len(task.edit_scope.editable) > cls._MAX_EDITABLE:
                return (f"Task {task.id} edits {len(task.edit_scope.editable)} files — "
                        "too broad; split into patch-sized tasks (<=3 files).")
            if not has_section(md, task.id):  # md is non-empty (guarded above)
                return (f"Task {task.id} is in the skeleton but not described in plan_md; "
                        f"every skeleton task must have a '## {task.id}:' section.")
        for dep in plan.deps:
            if dep.task_id not in ids or dep.depends_on not in ids:
                return ("Plan has dependency referencing unknown task: "
                        f"{dep.task_id}->{dep.depends_on}.")
        if cls._has_cycle(ids, plan.deps):
            return "Plan dependency graph has a cycle."
        return None

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


# Shared by AcceptanceGate (ill-formed floor) and AcceptanceCritic (adequacy). The
# acceptance layer is allowed to iterate a lot: the oracle↔critic loop is the harness
# *refusing to build against a gameable spec*, which is the behaviour we want. We only
# escalate to a human once it is clearly not converging, so the bound is deliberately
# loose — it is a non-termination backstop, not a quality knob.
ACCEPTANCE_REPAIR_BUDGET = 100


def _acceptance_repair_count(state) -> int:
    """Bounces back to acceptance_oracle from either the gate or the critic."""
    return sum(1 for t in state.history
               if t.trigger is TriggerKind.GATE and t.to_node == "acceptance_oracle")


class AcceptanceGate(GateNode):
    """Deterministic floor on the AcceptanceSpec: it must have at least one check and
    each check must be a runnable command (not prose). Task-DEPENDENT adequacy is the
    acceptance_critic's job, NOT this gate's."""

    name = "acceptance_gate"
    layer = Layer.ACCEPTANCE
    repair_budget = ACCEPTANCE_REPAIR_BUDGET
    phase = Phase.PLANNING

    def check(self, state) -> str | None:
        return self._invalid_hint(state.acceptance)

    def escalate_query(self, hint: str) -> str:
        return f"Acceptance check still ill-formed after redesign: {hint}"

    def _repair_count(self, state) -> int:
        return _acceptance_repair_count(state)

    @staticmethod
    def _invalid_hint(spec) -> str | None:
        if spec is None or not spec.checks:
            return "Acceptance spec has no checks; design at least one runnable check."
        for i, chk in enumerate(spec.checks, start=1):
            floor = validation_floor_hint(chk.command)
            if floor is not None:
                return f"Acceptance check {i} ({chk.criterion!r}) command {floor}"
        return None
