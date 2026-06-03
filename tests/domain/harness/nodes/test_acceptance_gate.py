import asyncio

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.gates import AcceptanceGate
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Layer, SessionState, Transition, TriggerKind,
    VerdictKind,
)


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


def _spec(*commands):
    return AcceptanceSpec(checks=tuple(
        AcceptanceCheck(criterion=f"c{i}", command=c) for i, c in enumerate(commands)))


@pytest.mark.asyncio
async def test_advances_on_well_formed_spec():
    s = SessionState(acceptance=_spec("printf '%s' \"$E\" | diff - hello.txt"))
    res = await AcceptanceGate().run(_ctx(s))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_repairs_on_empty_spec():
    res = await AcceptanceGate().run(_ctx(SessionState(acceptance=AcceptanceSpec())))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.ACCEPTANCE


@pytest.mark.asyncio
async def test_repairs_on_prose_check():
    s = SessionState(acceptance=_spec("Check that hello.txt is correct"))
    res = await AcceptanceGate().run(_ctx(s))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.ACCEPTANCE


@pytest.mark.asyncio
async def test_escalates_after_budget():
    bounces = tuple(
        Transition(from_node="acceptance_gate", to_node="acceptance_oracle",
                   trigger=TriggerKind.GATE, reason="r", ts_iso="t")
        for _ in range(2))
    s = SessionState(acceptance=AcceptanceSpec(), history=bounces)
    res = await AcceptanceGate().run(_ctx(s))
    assert res.verdict.kind is VerdictKind.ESCALATE
