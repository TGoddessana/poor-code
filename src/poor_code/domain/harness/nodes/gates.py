# src/poor_code/domain/harness/nodes/gates.py
"""Gates — deterministic [C] nodes that emit a Verdict (never an output object).
The Verdict is what makes the graph *cycle*: route() turns repair(layer) into a
back-edge to that layer's shallowest producer (design.md §6/§16/§18)."""
from __future__ import annotations

from poor_code.domain.harness.ledger import has_section
from poor_code.domain.harness.node import GateNode
from poor_code.domain.session.models import (
    CodeContext, GroundingStatus, Layer, Phase, Plan, StepKind, TriggerKind,
)


class UnderstandingGate(GateNode):
    """Guards the understanding layer in TRUST MODE: the Explorer decides when it has
    searched enough, and any terminal judgment it returns is honoured — candidates found,
    a greenfield call, OR a written search_notes diagnosis ("I looked; here's what I saw")
    all advance. Only a content-free result (no candidates, not greenfield, no notes) is
    treated as a degenerate/failed exploration worth ONE re-search; a second empty pass
    escalates. search_notes is NOT discarded on advance — the implementer consumes it as
    an UNVERIFIED note, so a not_found-with-diagnosis flows forward instead of bouncing."""

    name = "understanding_gate"
    layer = Layer.UNDERSTANDING
    repair_budget = 1
    phase = Phase.LOCATING
    requires = (CodeContext,)
    produces = ()

    def check(self, state) -> str | None:
        cc = state.understanding or CodeContext()
        if (cc.candidates or cc.grounding is GroundingStatus.GREENFIELD
                or cc.search_notes.strip()):
            return None
        return "Explorer produced no candidates and no diagnosis; widen the search."

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
    advisable = True   # POOR_CODE_ADVISORY_GATES → don't bounce; let the plan flow on
    requires = (Plan,)
    produces = ()

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
            file_paths = {f.path for f in plan.file_plan}
            if plan.file_plan:
                for p in task.edit_scope.editable:
                    if p not in file_paths:
                        return (f"Task {task.id} edits {p!r} but it is not in file_plan; "
                                "every editable path must have a file_plan entry.")
            placeholders = ("todo", "tbd", "fixme", "implement later", "fill in")
            for s in task.steps:
                if s.kind in (StepKind.TEST, StepKind.IMPL):
                    if not s.body.strip():
                        return f"Step {s.id} ({s.kind.value}) has an empty body; write the code."
                    low = s.body.lower()
                    if any(ph in low for ph in placeholders):
                        return (f"Step {s.id} body contains a placeholder "
                                "(TODO/TBD/FIXME/'implement later'); write the real code.")
                    if not s.file.strip():
                        return f"Step {s.id} ({s.kind.value}) has no target file."
                elif s.kind is StepKind.RUN:
                    if not s.run.strip() or not s.expected.strip():
                        return (f"Step {s.id} (run) needs both a run command and an "
                                "expected result.")
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
