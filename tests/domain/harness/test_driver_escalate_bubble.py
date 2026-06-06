import asyncio
import pytest
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.graph import EdgeTable
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Verdict, VerdictKind,
)


class _Escalate:
    name = "g"; phase = Phase.IMPLEMENTING
    async def run(self, ctx):
        return NodeResult(verdict=Verdict(kind=VerdictKind.ESCALATE, query="need help"))


@pytest.mark.asyncio
async def test_driver_records_escalate_for_bubbling_but_still_parks_at_user():
    edges = EdgeTable(forward={}, back_edges={})
    reg = NodeRegistry(); reg.register(_Escalate())
    driver = Driver(reg, edges.route)
    start = SessionState(cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="g"))
    final = await driver.run(start, asyncio.Event())
    # top-level: advanced to the 'user' park, AND recorded the escalate for a wrapping graph
    assert final.cursor.current_node == "user"
    assert driver.last_escape is not None and driver.last_escape.kind is VerdictKind.ESCALATE
