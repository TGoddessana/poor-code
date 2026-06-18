"""global_validator [A ★] — the whole-build finishing validator (verification v2).

The per-task VerifierNode judges each task's slice by OBSERVATION. This node is the same
idea at BUILD scope: after every task is done it drives the INTEGRATED system end-to-end
against the full acceptance criteria, hunts for CROSS-TASK regressions a single per-task
verifier cannot see, then emits a verdict. Like the Verifier it OBSERVES (bash + read/grep)
and never re-runs a model-authored bash "acceptance command" as an absolute floor — that
floor was the last thing that false-abandoned correct builds on their own `set -o pipefail`.

Two dispositions matter:
  • DEFAULT-ADVANCE — every task already passed its own verification, so the judge only
    overrides to repair when it OBSERVES a concrete regression; absent that, it advances.
  • BEST-EFFORT AT THE CAP — repairs are bounded (scoped single-task reopen first, then a
    full re-plan). When BOTH budgets are spent it does NOT escalate to a 'user' node (which
    is unregistered headless and parks → abandons a correct-on-disk build). It advances
    best-effort to the reporter and surfaces the unresolved note.

Two stages mirror the Verifier: ① an observe tool loop, then ② a forced structured verdict.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from poor_code.domain.harness.ledger import render_build_ledger, task_section
from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output)
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    AttemptStatus, ChangeSet, Layer, Phase, Plan, SessionState, TaskReopened,
    TaskStatus, Verdict, VerdictKind, effective_requirement)
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.glob import GlobTool
from poor_code.domain.tool.grep import GrepTool
from poor_code.domain.tool.list import ListTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry

MAX_FIXUPS = 2          # full re-plan fixups (the heavy fallback) before best-effort advance
MAX_SCOPED_FIXUPS = 2   # scoped (single-task) repairs before falling back to re-plan
MAX_ITERATIONS = 20
_TOOL_NAME = "assess_build"


def observe_tools() -> ToolRegistry:
    """The global validator OBSERVES the integrated build — it runs and inspects but never
    mutates: bash to drive (start servers, curl, feed inputs) + read/grep/glob/list to
    inspect. No write/edit, so finishing validation can't 'fix' what it is judging."""
    return ToolRegistry([BashTool(), ReadTool(), GrepTool(), GlobTool(), ListTool()])


_OBSERVE_SYSTEM = (
    "You are the whole-build Validator, the FINISHING step of the pipeline. Every task has "
    "already passed its OWN per-task verification. Your job: confirm the WHOLE build holds "
    "together — DRIVE the integrated system the way the CRITERIA say it is invoked (the real "
    "command / file / endpoint), OBSERVE its real behaviour with your tools, and hunt for a "
    "CROSS-TASK regression: one task's change breaking another's, or the assembled whole "
    "failing a criterion no single task exercised.\n"
    "NEVER DESTROY THE TASK'S INPUTS. Do NOT overwrite, empty, truncate, replace, move, or "
    "corrupt any file the task provided or named — the last run against those inputs is what "
    "gets graded. To probe an edge case, WRITE A SMALL THROWAWAY TEST IN $TMPDIR (a bash "
    "heredoc creating your own scratch input + script), never mutate the real files.\n"
    "Do NOT modify the implementation's code (you only run, inspect, and write throwaway "
    "tests under $TMPDIR). Verify by OBSERVATION, never assume from how the code looks. When "
    "you have observed enough to judge the whole build, stop calling tools."
)

_JUDGE_SYSTEM = (
    "From what you OBSERVED above, judge the WHOLE build against the CRITERIA. FIRST fill "
    "`checks` — one entry per criterion you exercised, with `observed` = the command you RAN "
    "and the real output you SAW, and `satisfied`.\n"
    "THEN choose the verdict. DEFAULT TO 'advance': every task already passed its own "
    "verification, so advance UNLESS you OBSERVED a concrete failure of the integrated build. "
    "Do NOT block on something you did not actually run and see fail.\n"
    "- 'advance': the integrated build holds; no observed cross-task regression.\n"
    "- 'repair_impl': you OBSERVED a regression pinnable to ONE task — set `culprit_task_id` "
    "to that task id (e.g. 't2'); only it is re-implemented (cheap). Cite the observed "
    "evidence in `hint`.\n"
    "- 'repair_plan': the whole decomposition is wrong (wrong files/tasks). Leave "
    "culprit_task_id empty.\n"
    "Trust ONLY observation. Call assess_build once."
)


class _BuildCheck(BaseModel):
    criterion: str
    observed: str = ""        # the command run + the real output seen ("" = not exercised)
    satisfied: bool = False


class _GVOut(BaseModel):
    checks: list[_BuildCheck] = []
    verdict: Literal["advance", "repair_impl", "repair_plan"]
    culprit_task_id: str = ""
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
    phase = Phase.FINALIZING
    requires = (Plan,)
    produces = ()

    def __init__(self, llm: _LLMClientLike, cwd: Path, tools: ToolRegistry | None = None) -> None:
        super().__init__(llm)
        self._cwd = Path(cwd)
        self._tools = tools if tools is not None else observe_tools()

    async def run(self, ctx: NodeContext) -> NodeResult:
        state = ctx.state
        state.require(Plan)
        history = await self._observe(ctx)
        out = validate_output(
            _GVOut, await self._dispatch(ctx, extra_messages=history), node=self.name)

        if out.verdict == "advance":
            return NodeResult(branch="pass")

        # A regression was OBSERVED → bounded repair. Scoped single-task reopen first (cheap),
        # then full re-plan, then best-effort advance (never escalate → 'user' park).
        hint = out.hint or "Global validation observed a regression; fix it."
        scoped = self._count(state, "implement_loop")
        culprit = out.culprit_task_id.strip()
        if (out.verdict == "repair_impl" and culprit and scoped < MAX_SCOPED_FIXUPS
                and self._is_done_task(state, culprit)):
            return NodeResult(
                output=TaskReopened(task_id=culprit),
                verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION, hint=hint))

        if self._count(state, "planner") < MAX_FIXUPS:
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint=hint))

        # Both budgets spent: best-effort advance. Escalating here routes to a 'user' node
        # that is unregistered headless → park → abandons a build that is correct on disk
        # (terminal-bench grades disk regardless). Report the unresolved note and move on.
        sink = getattr(ctx, "sink", None)
        if sink is not None and hasattr(sink, "node_repaired"):
            sink.node_repaired(
                self.name,
                f"fixup budget exhausted — proceeding best-effort despite unresolved "
                f"global validation: {hint}")
        return NodeResult(branch="pass")

    # stage ① — drive + observe tool loop (mirrors VerifierNode._observe)
    async def _observe(self, ctx: NodeContext) -> list[dict[str, Any]]:
        state = ctx.state
        seed: list[dict[str, Any]] = [
            {"role": "system", "content": _OBSERVE_SYSTEM},
            {"role": "user", "content": self._observe_prompt(state)},
        ]
        if ctx.sink is not None and hasattr(ctx.sink, "node_context"):
            phase = state.cursor.phase.value if state.cursor else ""
            ctx.sink.node_context(self.name, phase, seed)
        return await self._tool_loop(
            ctx, seed_messages=seed, tools=self._tools, cwd=self._cwd,
            max_iterations=MAX_ITERATIONS, leak_text=False)

    def _observe_prompt(self, state: SessionState) -> str:
        header = f"{render_position(self.name, state)}\n\n"
        if state.request is not None:
            header += f"ORIGINAL REQUEST:\n{state.request.raw_text}\n"
        req = effective_requirement(state)
        header += f"OVERALL GOAL:\n{req.summary}\n"
        changeset = build_changeset(state)
        changes = "\n\n".join(
            f"# task {tid}\n{clamp_tool_output(diff)}"
            for tid, diff in changeset.per_task) or "(none)"
        tasks = "\n".join(
            f"  - {t.id}: {t.title}" for t in state.plan.tasks) if state.plan else ""
        return (
            f"CRITERIA (the whole-build definition of done — verify EACH by observation):\n"
            f"{self._criteria(state)}\n\n"
            f"{header}\n"
            f"TASKS (each already passed its own verification; pin a culprit by id if one "
            f"regressed):\n{tasks}\n\n"
            f"COMPLETED WORK (ledger):\n{render_build_ledger(state)}\n\n"
            f"AGGREGATE CHANGES (per task — do not trust them; observe the real effect):\n"
            f"{changes}")

    @staticmethod
    def _criteria(state: SessionState) -> str:
        checks = state.acceptance.checks if state.acceptance else ()
        if checks:
            return "\n".join(f"  - {c.criterion}" for c in checks)
        req = effective_requirement(state)
        return ("\n".join(f"  - {a}" for a in req.acceptance)
                or "  (no explicit criteria — judge against the REQUEST and the task goals)")

    @staticmethod
    def _count(state: SessionState, to_node: str) -> int:
        return sum(1 for tr in state.history
                   if tr.from_node == "global_validator" and tr.to_node == to_node)

    @staticmethod
    def _is_done_task(state: SessionState, task_id: str) -> bool:
        plan = state.plan
        return plan is not None and any(
            t.id == task_id and t.status is TaskStatus.DONE for t in plan.tasks)

    # stage ② — verdict envelope
    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": "Emit your whole-build verdict, judging ONLY from "
             "what you observed."},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Judge the whole build against the criteria "
                                            "from observation.",
                             "parameters": inline_refs(_GVOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _GVOut

    def parse(self, args_json: str) -> _GVOut:
        return validate_output(_GVOut, args_json, node=self.name)
