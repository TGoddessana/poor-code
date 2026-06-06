import asyncio
import pytest
from poor_code.domain.harness.node import GateNode, NodeContext
from poor_code.domain.session.models import (
    SessionState, Phase, Layer, VerdictKind, TriggerKind, Transition,
)


class _AlwaysOk(GateNode):
    name = "g_ok"; layer = Layer.PLAN; repair_budget = 2; phase = Phase.PLANNING
    def check(self, state): return None


class _AlwaysBad(GateNode):
    name = "g_bad"; layer = Layer.PLAN; repair_budget = 2; phase = Phase.PLANNING
    def check(self, state): return "broken"


def _ctx(state): return NodeContext(state=state, cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_gate_advance_when_check_passes():
    r = await _AlwaysOk().run(_ctx(SessionState()))
    assert r.verdict.kind is VerdictKind.ADVANCE
    assert r.output is None


@pytest.mark.asyncio
async def test_gate_repair_when_check_fails_under_budget():
    r = await _AlwaysBad().run(_ctx(SessionState()))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.PLAN
    assert r.verdict.hint == "broken"


@pytest.mark.asyncio
async def test_gate_escalates_when_budget_exhausted():
    # two prior GATE bounces to the PLAN layer's shallowest producer (planner)
    hist = tuple(
        Transition(from_node="g_bad", to_node="planner", trigger=TriggerKind.GATE,
                   reason="r", ts_iso="t")
        for _ in range(2)
    )
    r = await _AlwaysBad().run(_ctx(SessionState(history=hist)))
    assert r.verdict.kind is VerdictKind.ESCALATE
    assert "broken" in r.verdict.query
