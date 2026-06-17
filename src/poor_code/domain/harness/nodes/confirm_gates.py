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
    Layer, Phase, Plan, Policy, Query, QueryKind, Requirement,
    TriggerKind, Verdict, VerdictKind, effective_requirement,
)

# The discrete "approve" action the widget offers as a selectable option. Approval is
# detected by IDENTITY against this exact string (the option the gate itself emitted),
# NOT by matching free text against a keyword list — so it works in any language and a
# user typing "좋아" can never be mis-read. A gate decision is approve / change-request:
# selecting this option = approve; ANY typed text = a change request (the steering hint).
APPROVE_OPTION = "승인하고 진행 (approve & proceed)"


class _ConfirmGate:
    name = ""
    query_id = ""
    layer: Layer = Layer.PLAN          # overridden per subclass
    repair_cap: int = 3

    async def run(self, ctx: NodeContext) -> NodeResult:
        if ctx.state.policy is Policy.FULL_AUTO:
            return NodeResult()                        # pass-through (advance)
        aq = self._fresh_answer(ctx.state)
        if aq is None:
            # Not answered yet, OR the only answer is stale (already consumed by a
            # prior reject bounce) — suspend for a fresh decision. The discrete approve
            # action is offered as a selectable widget option (identity-checked on
            # resume); typing anything instead is treated as a change request.
            return NodeResult(query=Query(
                id=self.query_id, kind=QueryKind.APPROVE,
                prompt=self._render(ctx.state),
                options=(APPROVE_OPTION,),
                rationale=("Select 'approve & proceed' to continue, or type the changes "
                           "you want to revise it.")))
        if self._is_approval(aq):
            return NodeResult()                        # advance
        hint = self._reject_hint(aq)
        if self._repair_count(ctx.state) >= self.repair_cap:
            # Cap reached: stop bouncing — advance anyway, warning the user. (This gate IS
            # the human; escalating a human's own gate back to them is pointless.)
            sink = getattr(ctx, "sink", None)
            if sink is not None and hasattr(sink, "node_repaired"):
                sink.node_repaired(
                    self.name,
                    f"repair cap ({self.repair_cap}) reached — proceeding despite "
                    f"unresolved comment: {hint}")
            return NodeResult()
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=self.layer, hint=hint))

    # --- answer access (mirrors interviewer's AnsweredQuery.response.answer/.chosen_option) ---
    def _answers(self, state) -> list:
        """All recorded answers for THIS gate's query_id, in order."""
        return [aq for aq in state.interview if aq.query.id == self.query_id]

    def _fresh_answer(self, state):
        """The user's latest AnsweredQuery for THIS gate IFF it is fresh (not yet consumed
        by a prior reject bounce). None when unanswered or when the latest answer is stale."""
        answers = self._answers(state)
        if len(answers) <= self._repair_count(state):
            return None
        return answers[-1]

    @staticmethod
    def _is_approval(aq) -> bool:
        """Approval is the discrete option the gate offered, matched by identity — not a
        keyword. Selecting it sets chosen_option to APPROVE_OPTION. A bare/empty submission
        with no chosen option also approves; ANY typed text is a change request."""
        resp = aq.response
        if (resp.chosen_option or "").strip() == APPROVE_OPTION:
            return True
        return not (resp.chosen_option or "").strip() and not (resp.answer or "").strip()

    @staticmethod
    def _reject_hint(aq) -> str:
        """The change request to feed the repaired layer: the typed text, or a chosen
        non-approve option."""
        resp = aq.response
        chosen = (resp.chosen_option or "").strip()
        if chosen and chosen != APPROVE_OPTION:
            return chosen
        return (resp.answer or "").strip()

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
    requires = (Requirement,)
    produces = ()

    def _render(self, state) -> str:
        return render_spec_md(effective_requirement(state), state.acceptance)


class PlanConfirmGate(_ConfirmGate):
    name = "plan_confirm_gate"
    phase = Phase.PLANNING
    query_id = "confirm_plan"
    layer = Layer.PLAN
    requires = (Plan,)
    produces = ()

    def _render(self, state) -> str:
        return render_plan_md(state.plan)
