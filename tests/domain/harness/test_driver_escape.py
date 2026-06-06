import asyncio
import pytest
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.graph import EdgeTable
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Verdict, VerdictKind, Layer,
)


class _RepairNode:
    name = "inner"
    phase = Phase.IMPLEMENTING
    async def run(self, ctx):
        return NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint="h"))


@pytest.mark.asyncio
async def test_driver_records_escape_when_route_returns_escape():
    # inner graph has NO PLAN back-edge → EdgeTable.route returns ESCAPE
    edges = EdgeTable(forward={}, back_edges={Layer.IMPLEMENTATION: "inner"})
    reg = NodeRegistry(); reg.register(_RepairNode())
    driver = Driver(reg, edges.route)
    start = SessionState(cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="inner"))
    final = await driver.run(start, asyncio.Event())
    assert driver.last_escape is not None
    assert driver.last_escape.layer is Layer.PLAN
    assert driver.last_escape.kind is VerdictKind.REPAIR


@pytest.mark.asyncio
async def test_driver_last_escape_is_none_on_normal_stop():
    # a node that just produces output and forwards to nothing (None) → normal park, no escape
    class _Plain:
        name = "p"; phase = Phase.IMPLEMENTING
        async def run(self, ctx): return NodeResult(output=None)
    edges = EdgeTable(forward={}, back_edges={})
    reg = NodeRegistry(); reg.register(_Plain())
    driver = Driver(reg, edges.route)
    start = SessionState(cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="p"))
    await driver.run(start, asyncio.Event())
    assert driver.last_escape is None
