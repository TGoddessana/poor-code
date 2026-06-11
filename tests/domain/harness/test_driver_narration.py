import asyncio
import pytest
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import Cursor, Layer, Phase, SessionState, Verdict, VerdictKind


class _RecordingSink:
    def __init__(self):
        self.entered = []
        self.produced = []
    def node_entered(self, node, phase, *, state=None, activity=""):
        self.entered.append((node, phase, state is not None))
    def node_produced(self, node, phase, *, result=None, headline="", detail=()):
        self.produced.append((node, result is not None))


class _Out:
    def apply_to(self, state):
        return state


class _OneShotNode:
    name = "explorer"
    phase = Phase.LOCATING
    async def run(self, ctx):
        return NodeResult(output=_Out())


class _VerdictOnlyNode:
    name = "plan_reviewer"
    phase = Phase.PLANNING

    async def run(self, ctx):
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR,
            layer=Layer.PLAN,
            hint="split task t2",
        ))


class _Registry:
    def __init__(self, node):
        self._node = node
        self._served = False
    def get(self, name):
        if self._served:
            return None  # park -> terminate
        self._served = True
        return self._node


@pytest.mark.asyncio
async def test_driver_emits_entered_with_state_and_produced_with_result():
    sink = _RecordingSink()
    state = SessionState(cursor=Cursor(phase=Phase.LOCATING, current_node="explorer"))
    driver = Driver(_Registry(_OneShotNode()), route=lambda *a: None)
    await driver.run(state, asyncio.Event(), sink=sink)
    assert sink.entered and sink.entered[0][0] == "explorer" and sink.entered[0][2] is True
    assert sink.produced and sink.produced[0] == ("explorer", True)


@pytest.mark.asyncio
async def test_driver_emits_produced_for_verdict_only_result():
    sink = _RecordingSink()
    state = SessionState(cursor=Cursor(phase=Phase.PLANNING, current_node="plan_reviewer"))
    driver = Driver(_Registry(_VerdictOnlyNode()), route=lambda *a: None)
    await driver.run(state, asyncio.Event(), sink=sink)
    assert sink.produced and sink.produced[0] == ("plan_reviewer", True)
