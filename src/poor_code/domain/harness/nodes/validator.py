"""validator [A, adversarial] — critiques the latest Attempt. It NEVER binds
pass/fail (that is the runner's job) and NEVER injects a command (that is the
Planner's how_to_validate). It only chooses a *direction*: advance, repair the
implementation, or repair the plan (weak validation). Its own loop is capped by
MAX_ADVERSARIAL_ROUNDS — at the cap it forces advance regardless of the model."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import AgentNode, NodeContext, NodeResult
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import Layer, Phase, SessionState, Verdict, VerdictKind

MAX_ADVERSARIAL_ROUNDS = 2
_TOOL_NAME = "judge"

_SYSTEM = (
    "You are an adversarial Validator. Inspect the implementer's patch against the "
    "TASK and its validation command. Decide one of: 'advance' (the change looks "
    "correct and complete), 'repair_impl' (the implementation has a hole — give a "
    "specific hint), or 'repair_plan' (the validation command is too weak to catch "
    "regressions — say why). You cannot run code or change the validation command. "
    "Also judge SCOPE with judgment, not a literal allowlist: EDITABLE SCOPE lists the "
    "files the task was expected to touch, but editing a closely-related file the task "
    "obviously needs is fine — e.g. fixing src/x.py and also editing its test "
    "tests/test_x.py, or a sibling in the same module. Only flag an edit as repair_impl "
    "for scope if it touches a CLEARLY UNRELATED file (different feature/module) with no "
    "bearing on this task; then say which file and why. Call judge once."
)


class _JudgeOut(BaseModel):
    verdict: str = "advance"   # advance | repair_impl | repair_plan
    hint: str = ""


class Validator(AgentNode):
    name = "validator"
    phase = Phase.IMPLEMENTING

    async def run(self, ctx: NodeContext) -> NodeResult:
        attempt = self._latest_attempt(ctx.state)
        if attempt is not None and attempt.adversarial_rounds >= MAX_ADVERSARIAL_ROUNDS:
            return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
        args_json = await self._dispatch(ctx)
        return NodeResult(verdict=self.parse(args_json))

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        task = self._active_task(state)
        attempt = self._latest_attempt(state)
        diff = "" if attempt is None or attempt.patch is None else attempt.patch.diff
        editable = ", ".join(task.edit_scope.editable) or "(unspecified)"
        forbidden = ", ".join(task.edit_scope.forbidden) or "(none)"
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"TASK: {task.title}\nPURPOSE: {task.purpose}\n"
                f"VALIDATION COMMAND: {task.how_to_validate}\n"
                f"EDITABLE SCOPE (guidance, judge with sense): {editable}\n"
                f"FORBIDDEN: {forbidden}\n\nPATCH:\n{diff or '(empty)'}")},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Judge the patch: advance / repair_impl / repair_plan.",
                             "parameters": inline_refs(_JudgeOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _JudgeOut

    def parse(self, args_json: str) -> Verdict:
        out = _JudgeOut.model_validate_json(args_json)
        if out.verdict == "repair_impl":
            return Verdict(kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION, hint=out.hint)
        if out.verdict == "repair_plan":
            return Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint=out.hint)
        return Verdict(kind=VerdictKind.ADVANCE)

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
