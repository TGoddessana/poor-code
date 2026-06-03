"""global_validator [A+C ★] — the finishing gate. CODE part (binding): re-run
EVERY task's how_to_validate in the work tree; all exit 0 → pass (→ reporter).
A failure means a regression (finishing task B broke task A). AGENT part
(advisory): analyze the ChangeSet + failures and hint which change to fix, then
emit repair(plan) → planner fixup. The fixup loop is capped by MAX_FIXUPS."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import AgentNode, NodeContext, NodeResult, _LLMClientLike
from poor_code.domain.harness.nodes.execution import run_shell
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    AttemptStatus, ChangeSet, Layer, SessionState, Verdict, VerdictKind)

MAX_FIXUPS = 2
_TOOL_NAME = "analyze_regression"

_SYSTEM = (
    "You are the Global Validator's analyst. Some task validations failed after all "
    "tasks were implemented — a regression. From the aggregate change set and the "
    "failing output, identify the likely culprit change and give a concrete hint for "
    "the planner to fix it. You do not bind pass/fail. Call analyze_regression once."
)


class _AnalyzeOut(BaseModel):
    hint: str = ""


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

    def __init__(self, llm: _LLMClientLike, cwd: Path) -> None:
        super().__init__(llm)
        self._cwd = cwd
        self._failures: list[tuple[str, int, str]] = []
        self._changeset = ChangeSet()

    async def run(self, ctx: NodeContext) -> NodeResult:
        plan = ctx.state.plan
        assert plan is not None, "global_validator requires a plan"
        failures: list[tuple[str, int, str]] = []
        for task in plan.tasks:
            code, out = await run_shell(task.how_to_validate, self._cwd, ctx.cancel)
            if code != 0:
                failures.append((task.id, code, out))
        if ctx.state.acceptance is not None:
            for chk in ctx.state.acceptance.checks:
                code, out = await run_shell(chk.command, self._cwd, ctx.cancel)
                if code != 0:
                    failures.append((f"acceptance:{chk.criterion[:40]}", code, out))
        if not failures:
            return NodeResult(branch="pass")

        fixups = sum(1 for tr in ctx.state.history
                     if tr.from_node == "global_validator" and tr.to_node == "planner")
        if fixups >= MAX_FIXUPS:
            summary = "; ".join(f"{tid} exit {code}" for tid, code, _ in failures)
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query=f"Global validation still failing after {MAX_FIXUPS} fixups: {summary}"))

        self._failures = failures
        self._changeset = build_changeset(ctx.state)
        args_json = await self._dispatch(ctx)
        hint = _AnalyzeOut.model_validate_json(args_json).hint or "Global validation failed."
        return NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint=hint))

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        fails = "\n\n".join(
            f"[{tid} exit {code}]\n{out[:1500]}" for tid, code, out in self._failures)
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"AGGREGATE CHANGES:\n{self._changeset.aggregate_diff[:4000] or '(none)'}\n\n"
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
