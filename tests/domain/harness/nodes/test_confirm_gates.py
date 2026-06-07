import asyncio

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.confirm_gates import SpecConfirmGate, PlanConfirmGate
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, AnsweredQuery, EditScope, Plan, Policy, Query,
    QueryKind, Requirement, SessionState, Task, UserResponse,
)


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


def _answered(query_id: str) -> AnsweredQuery:
    q = Query(id=query_id, kind=QueryKind.APPROVE, prompt="...")
    return AnsweredQuery(query=q, response=UserResponse(query_id=query_id, answer="ok"))


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


@pytest.mark.asyncio
async def test_already_answered_advances():
    s = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        interview=(_answered("confirm_spec"),))
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
        policy=Policy.SUPERVISED, plan=_PLAN, interview=(_answered("confirm_plan"),))
    res = await PlanConfirmGate().run(_ctx(s))
    assert res.query is None


@pytest.mark.asyncio
async def test_unrelated_answered_query_does_not_advance():
    # An answered query for a DIFFERENT gate must not satisfy this gate.
    s = SessionState(
        policy=Policy.SUPERVISED, requirement=_REQ, acceptance=_SPEC,
        interview=(_answered("confirm_plan"),))
    res = await SpecConfirmGate().run(_ctx(s))
    assert res.query is not None
