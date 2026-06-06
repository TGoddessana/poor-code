import asyncio
import pytest
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Requirement,
)


class _PhasedNode:
    name = "planner"
    phase = Phase.PLANNING
    async def run(self, ctx):
        return NodeResult(output=Requirement(summary="x"))


@pytest.mark.asyncio
async def test_driver_uses_node_phase_attribute():
    reg = NodeRegistry(); reg.register(_PhasedNode())
    # planner forwards to plan_gate (unregistered) -> park; cursor phase should be PLANNING
    start = SessionState(cursor=Cursor(phase=Phase.INTERVIEWING, current_node="planner"))
    final = await Driver(reg, route).run(start, asyncio.Event())
    assert final.cursor.phase is Phase.PLANNING


@pytest.mark.asyncio
async def test_driver_keeps_phase_when_node_has_no_phase_attr():
    class _NoPhase:
        name = "planner"
        async def run(self, ctx): return NodeResult(output=Requirement(summary="x"))
    reg = NodeRegistry(); reg.register(_NoPhase())
    start = SessionState(cursor=Cursor(phase=Phase.INTERVIEWING, current_node="planner"))
    final = await Driver(reg, route).run(start, asyncio.Event())
    assert final.cursor.phase is Phase.INTERVIEWING  # fallback: keep current
