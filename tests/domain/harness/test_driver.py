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
    reg.register(_LocatorStub())  # no 'interviewer' → park there

    checkpoints: list[str] = []
    driver = Driver(reg, route, on_step=lambda s: checkpoints.append(s.cursor.current_node))

    start = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="router"))
    final = await driver.run(start, asyncio.Event())

    # parked at unknown 'interviewer' after locator produced understanding
    assert final.cursor.current_node == "interviewer"
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
