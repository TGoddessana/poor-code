"""plan_reviewer — adversarial review of the Plan's DECOMPOSITION. Where PlanGate
checks per-task form (scope size, runnable validation, acyclic), this LLM critic
judges whether the plan is well-decomposed: it rejects the five pathologies our
bench died on and bounces back to the planner. Emits a Verdict, not output.
Modeled on acceptance_critic (gate→critic loop)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output,
)
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    Layer, Phase, SessionState, TriggerKind, Verdict, VerdictKind,
)

_TOOL_NAME = "emit_plan_review"

# After this many bounces back to the planner, accept the gate-valid plan and move
# on. Decomposition quality is a judgement call; without a stop the critic could
# loop. The bar below converges the common case in round 1; this cap is the
# forward-progress backstop (same rationale as acceptance_critic).
_CONVERGENCE_CAP = 2

_SYSTEM = (
    "You are the Plan Reviewer. The Plan has already passed a structural gate "
    "(scope size, runnable validation, acyclic deps). Judge only whether it is "
    "WELL-DECOMPOSED. Set ok=false (reject) when ANY of these five pathologies "
    "holds, and name the concrete instance in `violation`:\n"
    "1. OVER-DECOMPOSITION — more tasks than the requirement needs, or two tasks "
    "that change together and should be ONE task (e.g. 'add test' split from "
    "'implement it').\n"
    "2. SCOPE CREEP — a task builds something the Requirement/Acceptance does not "
    "ask for (e.g. a package.json in a Python project).\n"
    "3. DESTRUCTIVE ORDERING — a task writes before the code it depends on exists, "
    "or puts a test ahead of its implementation so it risks clobbering files.\n"
    "4. BROKEN VALIDATION — a how_to_validate that is runnable yet structurally "
    "CANNOT pass (e.g. `python3 -m __main__` whose __spec__ is None, or asserting "
    "a computed number nobody observed).\n"
    "5. PHANTOM FILE — a task targets a file absent from file_plan or from the "
    "chosen stack/environment.\n"
    "6. TYPE-INCONSISTENCY — a step references a symbol named differently from where "
    "another step defines it (e.g. clear_layers() defined but clearLayers() called), "
    "or uses a function no step defines.\n"
    "7. COVERAGE GAP — an Acceptance check has no task whose steps would satisfy it.\n"
    "If NONE hold, set ok=true. Be decisive: a single deliverable should be ONE "
    "task with one sane probe. Call emit_plan_review once."
)


def _plan_review_repair_count(state: SessionState) -> int:
    """Bounces from plan_reviewer back to the planner — separate from PlanGate's
    own structural repair budget so the two do not interfere."""
    return sum(1 for t in state.history
               if t.trigger is TriggerKind.GATE
               and t.from_node == "plan_reviewer"
               and t.to_node == "planner")


class _ReviewOut(BaseModel):
    ok: bool
    violation: str | None = None


class PlanReviewer(AgentNode):
    name = "plan_reviewer"
    phase = Phase.PLANNING

    def __init__(self, llm: _LLMClientLike) -> None:
        super().__init__(llm)

    async def run(self, ctx: NodeContext) -> NodeResult:
        out = validate_output(_ReviewOut, await self._dispatch(ctx), node=self.name)
        if out.ok:
            return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
        hint = out.violation or "Plan decomposition is unsound; replan."
        if _plan_review_repair_count(ctx.state) >= _CONVERGENCE_CAP:
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ADVANCE,
                hint=(f"accepted gate-valid plan after {_CONVERGENCE_CAP} "
                      f"replans; last (unmet) objection: {hint[:200]}")))
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint=hint))

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        req = state.requirement
        plan = state.plan
        summary = req.summary if req is not None else "(no requirement)"
        acceptance = "\n".join(
            f"  - {a}" for a in (req.acceptance if req is not None else ())
        ) or "  (none)"
        env = state.understanding.environment if state.understanding is not None else ""
        files = "\n".join(
            f"  - {s.path}: {s.responsibility}" for s in (plan.file_plan if plan else ())
        ) or "  (none)"
        tasks = "\n\n".join(
            f"  {t.id} [{', '.join(t.edit_scope.editable)}] {t.title}\n"
            f"      validate: {t.how_to_validate}\n"
            + "\n".join(
                f"      {s.id} {s.kind.value} {s.file}: {s.body[:200]}"
                for s in t.steps
            )
            for t in (plan.tasks if plan else ())
        ) or "  (none)"
        deps = "\n".join(
            f"  {d.task_id} depends on {d.depends_on}"
            for d in (plan.deps if plan else ())
        ) or "  (none)"
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"REQUIREMENT summary: {summary}\n"
                f"ACCEPTANCE:\n{acceptance}\n\n"
                f"ENVIRONMENT:\n{env or '(none)'}\n\n"
                f"FILE PLAN:\n{files}\n\n"
                f"TASKS:\n{tasks}\n\n"
                f"DEPS:\n{deps}")},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Report whether the plan decomposition is sound.",
                             "parameters": inline_refs(_ReviewOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _ReviewOut

    def parse(self, args_json: str) -> object:  # unused; run() handles verdict inline
        return _ReviewOut.model_validate_json(args_json)
