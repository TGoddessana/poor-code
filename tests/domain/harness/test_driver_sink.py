import asyncio
import pytest
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import (
    Cursor, Phase, Request, RequestKind, SessionState,
)


class _RouterStub:
    name = "router"
    async def run(self, ctx):
        return NodeResult(output=Request(raw_text="x", kind=RequestKind.ENGINEERING))


class _RecordingSink:
    def __init__(self):
        self.entered = []
    def node_entered(self, node, phase):
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
