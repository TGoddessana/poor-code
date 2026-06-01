import asyncio

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.gates import UnderstandingGate
from poor_code.domain.session.models import (
    CodeContext, CodeRef, Layer, SessionState, Transition, TriggerKind, VerdictKind,
)


def _ctx(state: SessionState) -> NodeContext:
    return NodeContext(state=state, cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_advances_when_candidates_present():
    cc = CodeContext(candidates=(CodeRef(file="a.py", symbol="x"),))
    res = await UnderstandingGate().run(_ctx(SessionState(understanding=cc)))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_repairs_understanding_when_no_candidates():
    res = await UnderstandingGate().run(_ctx(SessionState(understanding=CodeContext())))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.UNDERSTANDING


@pytest.mark.asyncio
async def test_escalates_after_repair_budget_exhausted():
    # A prior gate-triggered bounce back to the locator already happened.
    prior = Transition(from_node="understanding_gate", to_node="locator",
                       trigger=TriggerKind.GATE, reason="repair", ts_iso="t")
    state = SessionState(understanding=CodeContext(), history=(prior,))
    res = await UnderstandingGate().run(_ctx(state))
    assert res.verdict.kind is VerdictKind.ESCALATE
