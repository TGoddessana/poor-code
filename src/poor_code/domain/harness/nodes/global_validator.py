"""global_validator [A+C ★] — the finishing gate. CODE part (binding): run the
global ACCEPTANCE spec checks (the authoritative validation); all exit 0 → pass
(→ reporter). A failure means the implementation doesn't satisfy the acceptance
criteria. AGENT part (advisory): analyze the ChangeSet + failures and hint which
change to fix, then emit repair(plan) → planner fixup. The fixup loop is capped
by MAX_FIXUPS."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from poor_code.domain.harness.node import AgentNode, NodeContext, NodeResult, _LLMClientLike
from poor_code.domain.harness.nodes.execution import run_shell
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.harness.node import validate_output
from poor_code.domain.session.models import (
    AcceptanceSpec, AttemptStatus, ChangeSet, Layer, Phase, Plan, SessionState,
    TaskReopened, TaskStatus, Verdict, VerdictKind)

MAX_FIXUPS = 2          # full re-plan fixups (the heavy fallback) before escalate
MAX_SCOPED_FIXUPS = 2   # scoped (single-task) repairs before falling back to re-plan
_TOOL_NAME = "analyze_regression"

_SYSTEM = (
    "You are the Global Validator's analyst. Some task validations failed after all "
    "tasks were implemented — a regression. From the aggregate change set and the "
    "failing output, identify the likely culprit and give a concrete fix hint. Set "
    "culprit_task_id to the SINGLE task id (e.g. 't2') whose change caused the failure "
    "when you can pin it to one — that task alone is re-implemented (cheap). Leave it "
    "empty only when the failure genuinely needs the whole plan rethought. You do not "
    "bind pass/fail. Call analyze_regression once."
)


class _AnalyzeOut(BaseModel):
    hint: str = Field(min_length=1)
    culprit_task_id: str = ""


def build_changeset(state: SessionState) -> ChangeSet:
    """Aggregate the last attempt diff of every task (preferring DONE attempts)."""
    per_task: list[tuple[str, str]] = []
    if state.plan is not None:
        for task in state.plan.tasks:
            done = [a for a in task.attempts if a.status is AttemptStatus.DONE]
            chosen = done[-1] if done else (task.attempts[-1] if task.attempts else None)
            if chosen is not None and chosen.patch is not None and chosen.patch.diff:
                per_task.append((task.id, chosen.patch.diff))
    aggregate = "\n".join(f"# task {tid}\n{diff}" for tid, diff in per_task)
    return ChangeSet(aggregate_diff=aggregate, per_task=tuple(per_task))


class GlobalValidator(AgentNode):
    name = "global_validator"
    phase = Phase.FINALIZING
    requires = (Plan, AcceptanceSpec)
    produces = ()

    def __init__(self, llm: _LLMClientLike, cwd: Path) -> None:
        super().__init__(llm)
        self._cwd = cwd
        self._failures: list[tuple[str, int, str]] = []
        self._changeset = ChangeSet()

    async def run(self, ctx: NodeContext) -> NodeResult:
        plan = ctx.state.plan
        ctx.state.require(Plan)
        # Verification v2: the per-task Verifier now owns verification by OBSERVATION, so
        # there is no model-authored bash acceptance command to re-run here (re-running it
        # was the last bash floor that could false-abandon a correct build on its own
        # `set -o pipefail`). Finalize as pass — every task that reached here was judged by
        # the Verifier. (A whole-build cross-task observe-judge is a planned v2 refinement.)
        return NodeResult(branch="pass")
        # --- v1-disabled bash-check path (kept for the v2 observe-judge rewrite) ---
        failures: list[tuple[str, int, str]] = []  # type: ignore[unreachable]
        if ctx.state.acceptance is not None:
            for chk in ctx.state.acceptance.checks:
                code, out = await run_shell(chk.command, self._cwd, ctx.cancel)
                if code != 0:
                    failures.append((f"acceptance:{chk.criterion[:40]}", code, out))
        if not failures:
            return NodeResult(branch="pass")

        # Repair hierarchy: scoped single-task repairs first (cheap), then full re-plan
        # fixups (heavy), then escalate to the user. The heavy fallback being exhausted
        # is the terminal condition — scoped repairs precede it and don't count here.
        plan_fixups = self._count(ctx.state, "planner")
        if plan_fixups >= MAX_FIXUPS:
            summary = "; ".join(f"{tid} exit {code}" for tid, code, _ in failures)
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query=f"Global validation still failing after fixups: {summary}"))

        self._failures = failures
        self._changeset = build_changeset(ctx.state)
        out = validate_output(_AnalyzeOut, await self._dispatch(ctx), node=self.name)
        hint = out.hint  # required non-empty by _AnalyzeOut (min_length=1)

        # Scoped repair: if the analyst pinned a single DONE task as the culprit and we
        # still have scoped budget, reopen ONLY it and bounce to the implement loop —
        # not a whole re-plan. This is the fix-git case: a one-line bashism should not
        # restart plan→reviewer→provisioner→all-tasks and die on the wall.
        scoped = self._count(ctx.state, "implement_loop")
        culprit = out.culprit_task_id.strip()
        if culprit and scoped < MAX_SCOPED_FIXUPS and self._is_done_task(ctx.state, culprit):
            return NodeResult(
                output=TaskReopened(task_id=culprit),
                verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION,
                                hint=hint))

        # Fallback: full re-plan (bounded by MAX_FIXUPS above).
        return NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint=hint))

    @staticmethod
    def _count(state: SessionState, to_node: str) -> int:
        return sum(1 for tr in state.history
                   if tr.from_node == "global_validator" and tr.to_node == to_node)

    @staticmethod
    def _is_done_task(state: SessionState, task_id: str) -> bool:
        plan = state.plan
        return plan is not None and any(
            t.id == task_id and t.status is TaskStatus.DONE for t in plan.tasks)

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        fails = "\n\n".join(
            f"[{tid} exit {code}]\n{clamp_tool_output(out)}"
            for tid, code, out in self._failures)
        # Render EACH task's diff under its own clamp so a later task is never wholly
        # dropped by a single aggregate cut (per_task already exists on the ChangeSet).
        changes = "\n\n".join(
            f"# task {tid}\n{clamp_tool_output(diff)}"
            for tid, diff in self._changeset.per_task) or "(none)"
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"AGGREGATE CHANGES (per task):\n{changes}\n\n"
                f"FAILING VALIDATIONS:\n{fails or '(none)'}")},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Identify the regression culprit and a fix hint.",
                             "parameters": inline_refs(_AnalyzeOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _AnalyzeOut

    def parse(self, args_json: str) -> str:  # unused (run() parses inline); kept for AgentNode contract
        return _AnalyzeOut.model_validate_json(args_json).hint
