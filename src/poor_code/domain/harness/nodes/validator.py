"""validator [A, adversarial] — critiques the latest Attempt. It NEVER binds
pass/fail (that is the runner's job) and NEVER injects a command (that is the
Planner's how_to_validate). It only chooses a *direction*: advance, repair the
implementation, or repair the plan (weak validation). Its own loop is capped by
MAX_ADVERSARIAL_ROUNDS — at the cap it forces advance regardless of the model."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from poor_code.domain.harness.ledger import render_build_ledger, task_section, render_acceptance
from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output)
from poor_code.domain.harness.nodes.execution import run_shell
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    ChecksObserved, Layer, Phase, SessionState, Verdict, VerdictKind)

MAX_ADVERSARIAL_ROUNDS = 2
_TOOL_NAME = "judge"


_SYSTEM = (
    "You are an adversarial Validator with REAL EXECUTION RESULTS in hand (see OBSERVED). "
    "The acceptance spec is the whole target; this task is one step toward it. Decide: "
    "'advance' (this patch is correct and regresses NO already-green acceptance check), "
    "'repair_impl' (a hole — cite the failing OBSERVED check and give a specific hint), or "
    "'repair_plan' (the plan/task is mis-scoped — say why). Trust OBSERVED over the patch's "
    "narrative. Judge SCOPE with sense (a closely-related file is fine; only flag clearly "
    "unrelated edits). Call judge once."
)


class _JudgeOut(BaseModel):
    verdict: Literal["advance", "repair_impl", "repair_plan"]
    hint: str = ""


class Validator(AgentNode):
    name = "validator"
    phase = Phase.IMPLEMENTING

    def __init__(self, llm: _LLMClientLike, cwd: Path = Path(".")) -> None:
        super().__init__(llm)
        self._cwd = cwd
        # [(criterion, passed, output_tail)] from the real acceptance run; default so
        # build_messages is safe if run() never populated it (e.g. direct test of msgs).
        self._observed: list[tuple[str, bool, str]] = []

    async def run(self, ctx: NodeContext) -> NodeResult:
        attempt = self._latest_attempt(ctx.state)
        if attempt is not None and attempt.adversarial_rounds >= MAX_ADVERSARIAL_ROUNDS:
            return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
        self._observed = await self._run_acceptance(ctx)  # ground truth → build_messages
        args_json = await self._dispatch(ctx)
        verdict = self.parse(args_json)
        results = tuple((crit, passed) for crit, passed, _ in self._observed)
        return NodeResult(verdict=verdict, output=ChecksObserved(results=results))

    async def _run_acceptance(self, ctx: NodeContext) -> list[tuple[str, bool, str]]:
        """Run every acceptance check for real; the validator judges from observed
        reality, not the implementer's claims. Output is tailed to keep prompts bounded."""
        out: list[tuple[str, bool, str]] = []
        checks = ctx.state.acceptance.checks if ctx.state.acceptance else ()
        for c in checks:
            code, text = await run_shell(c.command, self._cwd, ctx.cancel)
            out.append((c.criterion, code == 0, clamp_tool_output(text, head=300, tail=1200)))
        return out

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        task = self._active_task(state)
        attempt = self._latest_attempt(state)
        diff = "" if attempt is None or attempt.patch is None else attempt.patch.diff
        editable = ", ".join(task.edit_scope.editable) or "(unspecified)"
        forbidden = ", ".join(task.edit_scope.forbidden) or "(none)"
        accept = render_acceptance(state)
        observed = self._render_observed()
        task_md = task_section(state.plan, task.id) if state.plan else task.title
        ledger = render_build_ledger(state)
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"ACCEPTANCE SPEC (the whole target; judge PROGRESS + NO-REGRESSION, not full pass):\n"
                f"{accept}\n\nOBSERVED (real execution of the acceptance checks just now):\n"
                f"{observed}\n\nCOMPLETED WORK (ledger):\n{ledger}\n\n"
                f"THIS TASK:\n{task_md}\nEDITABLE (guidance): {editable}\n"
                f"FORBIDDEN: {forbidden}\n\nPATCH:\n{diff or '(empty)'}")},
        ]

    def _render_observed(self) -> str:
        if not self._observed:
            return "  (not run)"
        lines = []
        for crit, passed, tail in self._observed:
            status = "PASS" if passed else "FAIL"
            lines.append(f"  - {crit} -> {status}" + (f"\n    {tail}" if tail else ""))
        return "\n".join(lines)

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Judge the patch: advance / repair_impl / repair_plan.",
                             "parameters": inline_refs(_JudgeOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _JudgeOut

    def parse(self, args_json: str) -> Verdict:
        out = validate_output(_JudgeOut, args_json, node=self.name)
        if out.verdict == "repair_impl":
            return Verdict(kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION,
                           hint=out.hint or self._synth_hint())
        if out.verdict == "repair_plan":
            return Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN,
                           hint=out.hint or self._synth_hint())
        return Verdict(kind=VerdictKind.ADVANCE)

    def _synth_hint(self) -> str:
        """A repair verdict with no hint wastes a retry. Synthesize one
        deterministically from the failing OBSERVED checks (their tails carry the
        real error) so the implementer gets something actionable."""
        fails = [f"{crit}: {tail}".strip() if tail else crit
                 for crit, passed, tail in self._observed if not passed]
        return ("Failing checks:\n" + "\n".join(fails)) if fails else \
            "Validation failed; fix the implementation."

    @staticmethod
    def _active_task(state: SessionState):
        assert state.plan is not None and state.cursor is not None
        task = next((t for t in state.plan.tasks if t.id == state.cursor.task_id), None)
        assert task is not None, f"cursor task_id {state.cursor.task_id!r} not in plan"
        return task

    @classmethod
    def _latest_attempt(cls, state: SessionState):
        task = cls._active_task(state)
        return task.attempts[-1] if task.attempts else None
