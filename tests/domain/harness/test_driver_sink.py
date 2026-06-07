import asyncio
import pytest
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import (
    Cursor, Layer, Phase, Request, RequestKind, SessionState, Verdict, VerdictKind,
)


class _RouterStub:
    name = "router"
    async def run(self, ctx):
        return NodeResult(output=Request(raw_text="x", kind=RequestKind.ENGINEERING),
                          branch="engineering")


class _RecordingSink:
    def __init__(self):
        self.entered = []
    def node_entered(self, node, phase, *, state=None, activity=""):
        self.entered.append((node, phase))


def _route(node, result, state):
    return None  # terminal after one node


@pytest.mark.asyncio
async def test_driver_emits_node_entered_for_each_node():
    reg = NodeRegistry()
    reg.register(_RouterStub())
    sink = _RecordingSink()
    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="x", kind=RequestKind.ENGINEERING),
    )
    await Driver(reg, _route).run(start, asyncio.Event(), sink=sink)
    assert sink.entered == [("router", "routing")]


class _RepairNode:
    name = "eng_gate"
    async def run(self, ctx):
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION,
            hint="Edited path outside editable scope: astropy/io/ascii/tests/test_qdp.py"))


class _RepairRecordingSink:
    def __init__(self):
        self.entered = []
        self.repaired = []
    def node_entered(self, node, phase, *, state=None, activity=""):
        self.entered.append(node)
    def node_repaired(self, node, detail):
        self.repaired.append((node, detail))


@pytest.mark.asyncio
async def test_driver_emits_repair_hint_to_sink():
    # Why: a node's REPAIR verdict carries the reason it bounced (e.g. eng_gate's
    # scope violation). That reason was invisible — only `▸ node` was logged. Surface
    # it so headless runs show WHY a gate sent work back.
    reg = NodeRegistry()
    reg.register(_RepairNode())
    sink = _RepairRecordingSink()
    start = SessionState(
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="eng_gate"),
        request=Request(raw_text="x", kind=RequestKind.ENGINEERING),
    )
    await Driver(reg, lambda n, r, s: None).run(start, asyncio.Event(), sink=sink)
    assert sink.repaired, "REPAIR hint should be emitted to the sink"
    node, detail = sink.repaired[0]
    assert node == "eng_gate"
    assert "outside editable scope" in detail
    assert "test_qdp.py" in detail


@pytest.mark.asyncio
async def test_driver_repair_without_node_repaired_method_does_not_break():
    # Sinks predating this hook (only node_entered) must keep working — the Driver
    # guards the call so a missing node_repaired never raises.
    reg = NodeRegistry()
    reg.register(_RepairNode())
    sink = _RecordingSink()  # has node_entered, NOT node_repaired
    start = SessionState(
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="eng_gate"),
        request=Request(raw_text="x", kind=RequestKind.ENGINEERING),
    )
    final = await Driver(reg, lambda n, r, s: None).run(start, asyncio.Event(), sink=sink)
    assert final.repair_hint == "Edited path outside editable scope: astropy/io/ascii/tests/test_qdp.py"


@pytest.mark.asyncio
async def test_driver_run_without_sink_still_works():
    reg = NodeRegistry()
    reg.register(_RouterStub())
    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="x", kind=RequestKind.ENGINEERING),
    )
    final = await Driver(reg, _route).run(start, asyncio.Event())
    assert final.request.kind is RequestKind.ENGINEERING
