"""Human confirmation gates. SUPERVISED: render md, suspend via Query once, then on
resume classify the recorded answer — APPROVAL advances; a reject-with-comment routes
to a bounded repair of the producing layer (the comment is the hint). FULL_AUTO
(headless): pass through. Reuses the interviewer's Query/suspend path.

Resume contract (mirrors interviewer.py + driver.py): a node suspends by returning
NodeResult(query=Query(...)); the Driver records it as state.pending_query and re-enters
the SAME node on resume (cursor unchanged). When the user answers, state.with_user_response
appends an AnsweredQuery(query=pending_query, response=...) to state.interview and clears
pending_query. So a gate detects it was already answered by finding its own query id among
state.interview's AnsweredQuery.query.id values.

Re-entry / idempotency (THE crux): on a reject the gate returns a REPAIR Verdict; the
Driver logs a GATE Transition (from_node=this gate, to_node=the layer's producer) and
back-edges to the producing layer, which re-runs and eventually re-enters THIS gate. The
OLD AnsweredQuery (the reject comment) is STILL in state.interview — nothing removes it —
so naively re-reading it would emit the SAME repair forever. We break the loop by
COUNTING: a reject is "consumed" exactly when it produced a GATE bounce from this gate
(state.history). When the number of answers recorded for our query_id is <= the number of
rejects we have already consumed, the latest answer is STALE — we re-query for a fresh one.
Only a FRESH answer (answers_seen > rejects_consumed) is acted upon. An APPROVAL never
creates a bounce, so once approved the gate advances and is never re-entered."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.render_md import render_plan_md, render_spec_md
from poor_code.domain.session.models import (
    Layer, Phase, Policy, Query, QueryKind, TriggerKind, Verdict, VerdictKind,
    effective_requirement,
)

# Stripped, case-folded answers that count as "approve, proceed".
_APPROVALS = frozenset({
    "", "approve", "approved", "ok", "okay", "yes", "y", "lgtm", "proceed",
})


class _ConfirmGate:
    name = ""
    query_id = ""
    layer: Layer = Layer.PLAN          # overridden per subclass
    repair_cap: int = 3

    async def run(self, ctx: NodeContext) -> NodeResult:
        if ctx.state.policy is Policy.FULL_AUTO:
            return NodeResult()                        # pass-through (advance)
        answer = self._fresh_answer(ctx.state)
        if answer is None:
            # Not answered yet, OR the only answer is stale (already consumed by a
            # prior reject bounce) — suspend for a fresh decision.
            return NodeResult(query=Query(
                id=self.query_id, kind=QueryKind.APPROVE,
                prompt=self._render(ctx.state),
                rationale="Approve to proceed, or reply with changes to revise."))
        if self._is_approval(answer):
            return NodeResult()                        # advance
        if self._repair_count(ctx.state) >= self.repair_cap:
            # Cap reached: stop bouncing — advance anyway, warning the user.
            sink = getattr(ctx, "sink", None)
            if sink is not None and hasattr(sink, "node_repaired"):
                sink.node_repaired(
                    self.name,
                    f"repair cap ({self.repair_cap}) reached — proceeding despite "
                    f"unresolved comment: {answer}")
            return NodeResult()
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=self.layer, hint=answer))

    # --- answer access (mirrors interviewer's AnsweredQuery.response.answer/.chosen_option) ---
    def _answers(self, state) -> list:
        """All recorded answers for THIS gate's query_id, in order."""
        return [aq for aq in state.interview if aq.query.id == self.query_id]

    def _fresh_answer(self, state) -> str | None:
        """The user's latest answer to THIS gate IFF it is fresh (not yet consumed by a
        prior reject bounce). None when unanswered or when the latest answer is stale."""
        answers = self._answers(state)
        if len(answers) <= self._repair_count(state):
            return None
        return self._answer_text(answers[-1])

    @staticmethod
    def _answer_text(aq) -> str:
        resp = aq.response
        chosen = (resp.chosen_option or "").strip()
        return chosen if chosen else (resp.answer or "")

    def _is_approval(self, answer: str) -> bool:
        return answer.strip().casefold() in _APPROVALS

    def _repair_count(self, state) -> int:
        """How many times THIS gate has already bounced to repair — i.e. rejects already
        consumed. Mirrors PlanGate._repair_count's history-counting pattern."""
        return sum(1 for t in state.history
                   if t.trigger is TriggerKind.GATE and t.from_node == self.name)

    def _render(self, state) -> str:                   # pragma: no cover - overridden
        raise NotImplementedError


class SpecConfirmGate(_ConfirmGate):
    name = "spec_confirm_gate"
    phase = Phase.INTERVIEWING
    query_id = "confirm_spec"
    layer = Layer.ACCEPTANCE

    def _render(self, state) -> str:
        return render_spec_md(effective_requirement(state), state.acceptance)


class PlanConfirmGate(_ConfirmGate):
    name = "plan_confirm_gate"
    phase = Phase.PLANNING
    query_id = "confirm_plan"
    layer = Layer.PLAN

    def _render(self, state) -> str:
        return render_plan_md(state.plan)
