import asyncio
import pytest
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import (
    Cursor, Phase, Query, QueryKind, Request, RequestKind, SessionState,
)


class _Done:
    name = "router"
    async def run(self, ctx):
        return NodeResult(output=Request(raw_text="x", kind=RequestKind.ENGINEERING),
                          branch="engineering")


class _Ask:
    name = "interviewer"
    async def run(self, ctx):
        return NodeResult(query=Query(id="q", kind=QueryKind.CLARIFY, prompt="why?"))


class _RecSink:
    def __init__(self):
        self.entered, self.finished = [], []
    def node_entered(self, node, phase, *, state=None, activity=""):
        self.entered.append(node)
    def node_finished(self, node, phase, duration_sec, status):
        self.finished.append((node, status, duration_sec))


def _terminal_route(node, result, state):
    return None


@pytest.mark.asyncio
async def test_node_finished_done():
    reg = NodeRegistry(); reg.register(_Done())
    sink = _RecSink()
    start = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
                         request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    await Driver(reg, _terminal_route).run(start, asyncio.Event(), sink=sink)
    assert len(sink.finished) == 1
    node, status, dur = sink.finished[0]
    assert node == "router" and status == "done" and dur >= 0.0


@pytest.mark.asyncio
async def test_node_finished_parked_on_query():
    reg = NodeRegistry(); reg.register(_Ask())
    sink = _RecSink()
    start = SessionState(cursor=Cursor(phase=Phase.INTERVIEWING, current_node="interviewer"))
    await Driver(reg, _terminal_route).run(start, asyncio.Event(), sink=sink)
    assert sink.finished[0][0] == "interviewer" and sink.finished[0][1] == "parked"
