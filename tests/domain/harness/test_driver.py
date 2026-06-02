import asyncio
import pytest
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.node import NodeResult, NodeContext
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Request, RequestKind, CodeContext, CodeRef,
)


class _RouterStub:
    name = "router"
    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=Request(raw_text="add x", kind=RequestKind.ENGINEERING))


class _LocatorStub:
    name = "locator"
    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=CodeContext(candidates=(CodeRef(file="a.py", symbol="x"),)))


@pytest.mark.asyncio
async def test_driver_runs_router_then_locator_then_parks():
    reg = NodeRegistry()
    reg.register(_RouterStub())
    reg.register(_LocatorStub())  # no 'understanding_gate' registered → park there

    checkpoints: list[str] = []
    driver = Driver(reg, route, on_step=lambda s: checkpoints.append(s.cursor.current_node))

    start = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="router"))
    final = await driver.run(start, asyncio.Event())

    # parked at unregistered 'understanding_gate' after locator produced understanding
    assert final.cursor.current_node == "understanding_gate"
    assert final.request is not None and final.request.kind is RequestKind.ENGINEERING
    assert final.understanding.candidates[0].symbol == "x"
    assert "locator" in checkpoints


@pytest.mark.asyncio
async def test_driver_stops_when_route_returns_none():
    class _Terminal:
        name = "router"
        async def run(self, ctx): return NodeResult(output=Request(raw_text="?", kind=RequestKind.LIGHTWEIGHT))
    reg = NodeRegistry(); reg.register(_Terminal())
    driver = Driver(reg, route)
    start = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="router"))
    final = await driver.run(start, asyncio.Event())
    # router lightweight → 'fast_path' (unknown) → park
    assert final.cursor.current_node == "fast_path"


@pytest.mark.asyncio
async def test_driver_suspends_on_query_and_keeps_cursor():
    from poor_code.domain.harness.node import NodeResult, NodeContext
    from poor_code.domain.session.models import Query, QueryKind

    class _AskStub:
        name = "interviewer"
        async def run(self, ctx):
            return NodeResult(query=Query(id="q1", kind=QueryKind.CLARIFY, prompt="why?"))

    reg = NodeRegistry()
    reg.register(_AskStub())
    driver = Driver(reg, route)
    start = SessionState(cursor=Cursor(phase=Phase.INTERVIEWING, current_node="interviewer"),
                         request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    final = await driver.run(start, asyncio.Event())

    assert final.pending_query is not None
    assert final.pending_query.id == "q1"
    assert final.cursor.current_node == "interviewer"   # cursor stayed; re-entrant
    # suspend did not append a transition
    assert all(t.to_node != "interviewer" or t.from_node != "interviewer"
               for t in final.history)


@pytest.mark.asyncio
async def test_driver_applies_requirement_and_routes_to_planner():
    from poor_code.domain.harness.node import NodeResult
    from poor_code.domain.session.models import Requirement

    class _DoneStub:
        name = "interviewer"
        async def run(self, ctx):
            return NodeResult(output=Requirement(summary="done"))

    reg = NodeRegistry()
    reg.register(_DoneStub())   # planner unregistered → park
    driver = Driver(reg, route)
    start = SessionState(cursor=Cursor(phase=Phase.INTERVIEWING, current_node="interviewer"),
                         request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    final = await driver.run(start, asyncio.Event())

    assert final.requirement is not None and final.requirement.summary == "done"
    assert final.cursor.current_node == "planner"   # forwarded, then parked


from poor_code.domain.session.models import Verdict, VerdictKind, Layer


class _GateNode:
    """Stateful dummy: REPAIR on first visit, ADVANCE on the second so the loop
    terminates (ADVANCE -> FORWARD interviewer -> unregistered -> park)."""
    name = "understanding_gate"
    def __init__(self):
        self.calls = 0
    async def run(self, ctx):
        self.calls += 1
        if self.calls == 1:
            return NodeResult(output=None, verdict=Verdict(
                kind=VerdictKind.REPAIR, layer=Layer.UNDERSTANDING, hint="widen X"))
        return NodeResult(output=None, verdict=Verdict(kind=VerdictKind.ADVANCE))


class _Explorer:
    name = "explorer"
    def __init__(self):
        self.seen_hint = "UNSET"
    async def run(self, ctx):
        self.seen_hint = ctx.state.repair_hint           # hint reached the node
        return NodeResult(output=CodeContext(candidates=()))


def _fake_route(node, result, state):
    # isolate the Driver from route.py topology: REPAIR -> explorer,
    # explorer -> gate, gate ADVANCE -> stop (park).
    v = result.verdict
    if v is not None and v.kind is VerdictKind.REPAIR:
        return "explorer"
    if node == "explorer":
        return "understanding_gate"
    return None


@pytest.mark.asyncio
async def test_driver_sets_repair_hint_on_repair_then_clears_on_codecontext():
    explorer = _Explorer()
    reg = NodeRegistry()
    reg.register(_GateNode())
    reg.register(explorer)
    state = SessionState(
        understanding=CodeContext(candidates=()),
        cursor=Cursor(phase=Phase.LOCATING, current_node="understanding_gate"),
    )
    # gate(call1)->REPAIR sets repair_hint; route->explorer reads it; explorer's
    # CodeContext clears it; gate(call2)->ADVANCE-> stop (park).
    final = await Driver(reg, _fake_route).run(state, asyncio.Event())
    assert explorer.seen_hint == "widen X"               # hint carried to explorer
    assert final.repair_hint is None                     # cleared on CodeContext apply
