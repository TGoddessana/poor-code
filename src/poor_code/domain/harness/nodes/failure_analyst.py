"""failure_analyst [A] — runs after a binding runner failure. Distills the
failure into a FeedbackEntry that the implementer reads on later attempts. It
holds no authority; it only writes to FeedbackMemory (Driver._apply handles it)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import AgentNode, validate_output
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import FeedbackEntry, Phase, SessionState

_TOOL_NAME = "emit_feedback"

_SYSTEM = (
    "You are the Failure Analyst. A validation command just failed. From the patch, "
    "the ENVIRONMENT, and the failure output, distill ONE concise, reusable lesson: "
    "the failure_type, the symptom, and a prevention_hint the implementer can apply "
    "next time.\n"
    "RUNTIME RULE: if the failure output shows a runtime/tool is missing "
    "('command not found', 'not found', 'No such file'), the prevention_hint MUST tell "
    "the implementer to SWITCH to a tool/runtime that is actually present in ENVIRONMENT "
    "(e.g. rewrite a Node server in Python if node is absent but python3 is present) — "
    "NOT to retry the same absent tool or to assume it will exist later.\n"
    "Call emit_feedback once."
)


class _FeedbackOut(BaseModel):
    failure_type: str = ""
    symptom: str = ""
    prevention_hint: str = ""


class FailureAnalyst(AgentNode):
    name = "failure_analyst"
    phase = Phase.IMPLEMENTING

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        task = next((t for t in (state.plan.tasks if state.plan else ())
                     if t.id == state.cursor.task_id), None)
        attempt = task.attempts[-1] if (task and task.attempts) else None
        rr = attempt.run_result if attempt else None
        diff = attempt.patch.diff if (attempt and attempt.patch) else ""
        out = "" if rr is None else rr.output
        env = state.understanding.environment if state.understanding else ""
        env_block = f"ENVIRONMENT (what is actually available here):\n{env}\n\n" if env else ""
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"TASK: {task.title if task else '?'}\n\n{env_block}"
                f"PATCH:\n{diff or '(empty)'}\n\n"
                f"FAILURE OUTPUT:\n{out[:2000] or '(none)'}")},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Emit one reusable failure lesson.",
                             "parameters": inline_refs(_FeedbackOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _FeedbackOut

    def parse(self, args_json: str) -> FeedbackEntry:
        out = validate_output(_FeedbackOut, args_json, node=self.name)
        return FeedbackEntry(failure_type=out.failure_type, symptom=out.symptom,
                             prevention_hint=out.prevention_hint, task_ref=self._task_ref)

    # the active task id is stamped onto the entry; set by run() override below
    _task_ref: str | None = None

    async def run(self, ctx):
        self._task_ref = ctx.state.cursor.task_id if ctx.state.cursor else None
        return await super().run(ctx)
