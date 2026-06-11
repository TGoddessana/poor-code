import asyncio

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.confirm_gates import (
    APPROVE_OPTION, SpecConfirmGate, PlanConfirmGate)
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, AnsweredQuery, EditScope, Layer, Plan, Policy,
    Query, QueryKind, Requirement, SessionState, Task, Transition, TriggerKind,
    UserResponse, VerdictKind,
)


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


def _approved(query_id: str) -> AnsweredQuery:
    """The user SELECTED the discrete approve option (sets chosen_option by identity)."""
    q = Query(id=query_id, kind=QueryKind.APPROVE, prompt="...", options=(APPROVE_OPTION,))
    return AnsweredQuery(query=q, response=UserResponse(
        query_id=query_id, answer=APPROVE_OPTION, chosen_option=APPROVE_OPTION))


def _commented(query_id: str, comment: str) -> AnsweredQuery:
    """The user typed a change request instead of selecting approve."""
    q = Query(id=query_id, kind=QueryKind.APPROVE, prompt="...", options=(APPROVE_OPTION,))
    return AnsweredQuery(query=q, response=UserResponse(query_id=query_id, answer=comment))


def _bounce(from_node: str, to_node: str) -> Transition:
    """A GATE back-edge transition, as the Driver logs it when a gate returns a
    REPAIR verdict (trigger=GATE, from_node=gate, to_node=layer producer)."""
    return Transition(from_node=from_node, to_node=to_node,
                      trigger=TriggerKind.GATE, reason="reject", ts_iso="2026-06-07T00:00:00")


_REQ = Requirement(summary="build fib", acceptance=("n=10->55",))
_SPEC = AcceptanceSpec(checks=(AcceptanceCheck("n=10->55", "curl ..."),))
_PLAN = Plan(
    plan_md="## t1: server.py — handler",
    tasks=(Task(id="t1", title="h", purpose="", edit_scope=EditScope(editable=("server.py",))),),
    deps=(),
)


@pytest.mark.asyncio
async def test_supervised_emits_query_then_advances():
    s = SessionState(policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC)
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.query is not None and res.query.kind == QueryKind.APPROVE
    assert "Goal" in res.query.prompt  # md rendered
    assert res.query.options == (APPROVE_OPTION,)  # discrete approve action offered


@pytest.mark.asyncio
async def test_already_answered_advances():
    s = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        interview=(_approved("confirm_spec"),))
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.query is None
    assert res.verdict is None and res.output is None  # plain advance


@pytest.mark.asyncio
async def test_headless_passes_through():
    s = SessionState(policy=Policy.FULL_AUTO, requirement=_REQ, acceptance=_SPEC)
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.query is None


@pytest.mark.asyncio
async def test_plan_confirm_renders_plan():
    s = SessionState(policy=Policy.SUPERVISED, plan=_PLAN)
    res = await PlanConfirmGate().run(_ctx(s))
    assert res.query is not None and "## t1" in res.query.prompt


@pytest.mark.asyncio
async def test_plan_confirm_already_answered_advances():
    s = SessionState(
        policy=Policy.SUPERVISED, plan=_PLAN, interview=(_approved("confirm_plan"),))
    res = await PlanConfirmGate().run(_ctx(s))
    assert res.query is None


@pytest.mark.asyncio
async def test_unrelated_answered_query_does_not_advance():
    # An answered query for a DIFFERENT gate must not satisfy this gate.
    s = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        interview=(_approved("confirm_plan"),))
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.query is not None


# --- Task 11: reject-with-comment → bounded layer repair ---

@pytest.mark.asyncio
async def test_reject_routes_to_repair():
    # Spec gate, a non-approval comment, no prior repair bounces → REPAIR ACCEPTANCE.
    s = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        interview=(_commented("confirm_spec", "add more edge cases"),))
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.query is None
    assert res.verdict is not None
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.ACCEPTANCE
    assert "add more edge cases" in (res.verdict.hint or "")


@pytest.mark.asyncio
async def test_plan_reject_routes_to_plan_layer():
    s = SessionState(
        policy=Policy.SUPERVISED, plan=_PLAN,
        interview=(_commented("confirm_plan", "split task t1"),))
    res = await PlanConfirmGate().run(_ctx(s))
    assert res.verdict is not None
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN
    assert "split task t1" in (res.verdict.hint or "")


@pytest.mark.asyncio
async def test_approval_advances():
    s = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        interview=(_approved("confirm_spec"),))
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.verdict is None and res.query is None and res.output is None


@pytest.mark.asyncio
async def test_typed_nonenglish_text_is_a_change_request_not_approval():
    # The old bug: a Korean "좋아" typed as free text was matched against an English
    # keyword set, failed, and was treated as a rejection that re-ran the oracle. Now
    # approval is the discrete option (identity), so typed text — in ANY language — is
    # unambiguously a change request. (To approve, the user selects the option.)
    s = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        interview=(_commented("confirm_spec", "좋아"),))
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.verdict is not None and res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.hint == "좋아"


@pytest.mark.asyncio
async def test_discrete_approve_advances_regardless_of_language():
    # Selecting the approve option advances by IDENTITY — no keyword list involved.
    s = SessionState(
        policy=Policy.SUPERVISED, plan=_PLAN, interview=(_approved("confirm_plan"),))
    res = await PlanConfirmGate().run(_ctx(s))
    assert res.verdict is None and res.query is None


@pytest.mark.asyncio
async def test_reject_cap_advances():
    # cap=3 prior bounces from this gate already in history → advance, no new repair.
    cap = SpecConfirmGate.repair_cap
    history = tuple(_bounce("spec_confirm_gate", "acceptance_oracle") for _ in range(cap))
    s = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        history=history,
        # cap+1 answers so the latest IS fresh relative to the cap bounces consumed.
        interview=tuple(_commented("confirm_spec", "still not good") for _ in range(cap + 1)),
    )
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.verdict is None and res.query is None and res.output is None


@pytest.mark.asyncio
async def test_no_infinite_loop_on_reentry():
    # Re-entry scenario: the gate emitted a query, got ONE reject, returned REPAIR,
    # the Driver logged ONE GATE bounce, the layer re-ran, and the gate is re-entered.
    # The SAME (now-consumed) reject AnsweredQuery is still in state.interview. The gate
    # must NOT emit the same repair again; with no NEW answer it re-queries for a fresh
    # decision (idempotency: answers_seen(1) <= rejects_consumed(1) → stale → re-query).
    gate = SpecConfirmGate()

    # 1) First reject → REPAIR.
    s1 = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        interview=(_commented("confirm_spec", "needs work"),))
    r1 = await gate.run(_ctx(s1))
    assert r1.verdict is not None and r1.verdict.kind is VerdictKind.REPAIR

    # 2) Driver logged the bounce; layer re-ran; gate re-entered with NO new answer.
    s2 = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        history=(_bounce("spec_confirm_gate", "acceptance_oracle"),),
        interview=(_commented("confirm_spec", "needs work"),))  # SAME stale answer
    r2 = await gate.run(_ctx(s2))
    assert r2.verdict is None              # NOT another repair → no loop
    assert r2.query is not None           # re-queries for a fresh decision

    # 3) User now answers afresh with approval → advance.
    s3 = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        history=(_bounce("spec_confirm_gate", "acceptance_oracle"),),
        interview=(_commented("confirm_spec", "needs work"),
                   _approved("confirm_spec")))
    r3 = await gate.run(_ctx(s3))
    assert r3.verdict is None and r3.query is None
