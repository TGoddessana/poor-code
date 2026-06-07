"""Human confirmation gates. SUPERVISED: render md, suspend via Query once, advance on
resume. FULL_AUTO (headless): pass through. Reuses the interviewer's Query/suspend path.

Resume contract (mirrors interviewer.py + driver.py): a node suspends by returning
NodeResult(query=Query(...)); the Driver records it as state.pending_query and re-enters
the SAME node on resume (cursor unchanged). When the user answers, state.with_user_response
appends an AnsweredQuery(query=pending_query, response=...) to state.interview and clears
pending_query. So a gate detects it was already answered by finding its own query id among
state.interview's AnsweredQuery.query.id values — exactly what _already_answered checks."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.render_md import render_plan_md, render_spec_md
from poor_code.domain.session.models import Policy, Query, QueryKind, effective_requirement


def _already_answered(state, query_id: str) -> bool:
    return any(aq.query.id == query_id for aq in state.interview)


class _ConfirmGate:
    name = ""
    query_id = ""

    async def run(self, ctx: NodeContext) -> NodeResult:
        if ctx.state.policy is Policy.FULL_AUTO:
            return NodeResult()                       # pass-through (advance)
        if _already_answered(ctx.state, self.query_id):
            return NodeResult()                       # resumed: advance
        return NodeResult(query=Query(
            id=self.query_id, kind=QueryKind.APPROVE,
            prompt=self._render(ctx.state),
            rationale="Approve to proceed, or reply with changes to revise."))

    def _render(self, state) -> str:                  # pragma: no cover - overridden
        raise NotImplementedError


class SpecConfirmGate(_ConfirmGate):
    name = "spec_confirm_gate"
    query_id = "confirm_spec"

    def _render(self, state) -> str:
        return render_spec_md(effective_requirement(state), state.acceptance)


class PlanConfirmGate(_ConfirmGate):
    name = "plan_confirm_gate"
    query_id = "confirm_plan"

    def _render(self, state) -> str:
        return render_plan_md(state.plan)
