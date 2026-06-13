"""completion_judge — the final completion decision, promoted from a deterministic
gate to an LLM judge that sits ON TOP of the objective floor.

WHY an agent node: not every coding problem has a clean mechanical pass/fail oracle.
Open-ended work ("refactor", "improve", ambiguous bugs) has no exit-0 'done'. And even
when an objective check exists it can be WRONG — too loose, mis-targeted, or structurally
broken (a check that errors regardless of the implementation, e.g. `set -o pipefail` under
dash). A deterministic gate is blind to all of that. The judge reads the request intent,
the patch, and the OBSERVED check results, and decides.

WHAT keeps it safe (the floor): the judge may DEMOTE (call a passing task not-done when the
checks miss the point) but may NEVER PROMOTE a task past a FAILING binding check. That hard
veto is mechanical, not prompt-trust — it is what stops a weak model from rubber-stamping
its own broken work (the false-completion bug). For an OPEN-ENDED task (no binding check)
the floor is empty, so the judge becomes the primary signal — exactly where determinism
never worked.

The node keeps the wiring name 'completion_gate' so the graph topology is unchanged."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from poor_code.domain.harness.ledger import render_acceptance, task_section
from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output)
from poor_code.domain.harness.nodes.execution import MAX_ATTEMPTS, _active
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    Layer, Phase, SessionState, TaskCompleted, Verdict, VerdictKind,
    effective_requirement)

_TOOL_NAME = "decide"

_SYSTEM = (
    "You are the Completion Judge — the final authority on whether THIS task is DONE. "
    "You are given OBSERVED objective check results that were just executed. Choose ONE "
    "verdict:\n"
    "- 'done': the task's goal is genuinely achieved.\n"
    "    * VERIFIABLE task (objective checks exist): choose done ONLY when the checks PASS. "
    "If they pass but do NOT actually capture the request (a wrong implementation would also "
    "pass them), choose 'repair_impl' instead. You may NOT call a task with FAILING checks "
    "done.\n"
    "    * OPEN-ENDED task (no objective check): judge holistically from the PATCH and the "
    "REQUEST intent — is the change real, complete, and on-target?\n"
    "- 'repair_impl': the implementation has a hole. Cite the failing OBSERVED check and "
    "give a concrete, actionable hint.\n"
    "- 'repair_plan': the task is mis-scoped — wrong files, wrong decomposition. Say why.\n"
    "- 'repair_accept': the CHECK ITSELF is broken — it errors or cannot pass regardless of a "
    "correct implementation. Signs: 'Illegal option', 'command not found', a missing "
    "tool/runtime, a shell incompatibility, or a hard-coded expectation nobody derived. The "
    "implementation is NOT at fault; the acceptance check must be redesigned.\n"
    "Trust OBSERVED over the patch's narrative. Call decide once."
)


class _DecisionOut(BaseModel):
    verdict: Literal["done", "repair_impl", "repair_plan", "repair_accept"]
    reason: str = ""


class CompletionJudge(AgentNode):
    # Wiring name retained: the graph edges reference 'completion_gate'. The class is the
    # LLM judge; only the implementation changed, not the node's identity in the topology.
    name = "completion_gate"
    phase = Phase.IMPLEMENTING

    def __init__(self, llm: _LLMClientLike) -> None:
        super().__init__(llm)

    async def run(self, ctx: NodeContext) -> NodeResult:
        state = ctx.state
        task, attempt = _active(state)
        rr = attempt.run_result if attempt is not None else None
        decision = self.parse(await self._dispatch(ctx))
        verdict, reason = decision.verdict, decision.reason
        passed = rr is not None and rr.passed
        has_binding = self._has_binding(state, task)

        # FLOOR VETO — never PROMOTE past a failing binding check. The judge may demote a
        # passing task, but a verifiable task whose checks FAIL can never be 'done'. (For an
        # OPEN-ENDED task has_binding is False, so the judge's 'done' stands.)
        if verdict == "done" and (attempt is None or (has_binding and not passed)):
            verdict = "repair_impl"
            reason = ("Objective acceptance checks do not pass yet — not done. "
                      + (reason or "")).strip()

        if verdict == "done":
            return NodeResult(
                output=TaskCompleted(task_id=task.id, attempt_id=attempt.id),
                branch="done")

        if verdict == "repair_impl":
            if len(task.attempts) >= MAX_ATTEMPTS:
                # Out of repair budget. If the objective floor actually passes, accept rather
                # than abandon working code (a judge stuck demoting passing work must not lose
                # it); otherwise escalate.
                if passed:
                    return NodeResult(
                        output=TaskCompleted(task_id=task.id, attempt_id=attempt.id),
                        branch="done")
                return NodeResult(verdict=Verdict(
                    kind=VerdictKind.ESCALATE, query=self._escalate_query(task, rr)))
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION,
                hint=reason or self._synth_hint(rr)))

        if verdict == "repair_plan":
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.REPAIR, layer=Layer.PLAN,
                hint=reason or self._synth_hint(rr)))

        # repair_accept → bubble to acceptance_oracle (Layer.ACCEPTANCE) to redesign the check.
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.ACCEPTANCE,
            hint=reason or self._synth_hint(rr)))

    @staticmethod
    def _has_binding(state: SessionState, task) -> bool:
        """A task is VERIFIABLE when an objective check exists for it: a global acceptance
        spec, or a task-level how_to_validate. Without either, completion is a judgment call."""
        if state.acceptance is not None and state.acceptance.checks:
            return True
        return bool(task.how_to_validate)

    @staticmethod
    def _synth_hint(rr) -> str:
        """A repair verdict with no model hint still needs something actionable — synthesize
        from the OBSERVED failures so the implementer/oracle gets the real error."""
        if rr is None:
            return "Validation did not pass; fix the implementation."
        fails = [crit for crit, ok in rr.check_results if not ok]
        body = rr.output or ""
        if fails:
            return (f"Failing checks: {', '.join(fails)}\n{body}").strip()
        return body or "Validation did not pass; fix the implementation."

    @staticmethod
    def _escalate_query(task, rr) -> str:
        tail = clamp_tool_output(rr.output, head=200, tail=600) if (rr and rr.output) else "(no output)"
        return f"Task {task.id} still failing after {MAX_ATTEMPTS} attempts: {tail}"

    # --- AgentNode hooks ---
    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        task, attempt = _active(state)
        rr = attempt.run_result if attempt is not None else None
        diff = "" if attempt is None or attempt.patch is None else attempt.patch.diff
        req = effective_requirement(state)
        request_text = state.request.raw_text if state.request is not None else req.summary
        accept_list = "\n".join(f"  - {a}" for a in req.acceptance) or "  (none stated)"
        kind = ("VERIFIABLE (objective checks exist — done requires them to PASS)"
                if self._has_binding(state, task)
                else "OPEN-ENDED (no objective check — judge from patch + intent)")
        floor = "PASS" if (rr is not None and rr.passed) else "FAIL"
        task_md = task_section(state.plan, task.id) if state.plan else task.title
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"REQUEST (the user's intent — what 'done' must mean):\n{request_text}\n\n"
                f"STATED ACCEPTANCE:\n{accept_list}\n\n"
                f"ACCEPTANCE SPEC (objective checks):\n{render_acceptance(state)}\n\n"
                f"TASK TYPE: {kind}\n"
                f"OBJECTIVE FLOOR: {floor}\n\n"
                f"OBSERVED (real check execution just now):\n{self._render_observed(rr)}\n\n"
                f"THIS TASK:\n{task_md}\n\n"
                f"PATCH (the change being judged):\n{diff or '(empty)'}")},
        ]

    @staticmethod
    def _render_observed(rr) -> str:
        if rr is None:
            return "  (no validation result)"
        lines = [f"  - {crit} -> {'PASS' if ok else 'FAIL'}" for crit, ok in rr.check_results]
        body = "\n".join(lines) if lines else "  (no per-check results)"
        if rr.output:
            body += "\n  output:\n" + clamp_tool_output(rr.output, head=400, tail=1100)
        return body

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": ("Decide whether the task is done, or what must "
                                             "be repaired (impl / plan / acceptance check)."),
                             "parameters": inline_refs(_DecisionOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _DecisionOut

    def parse(self, args_json: str) -> _DecisionOut:
        return validate_output(_DecisionOut, args_json, node=self.name)
