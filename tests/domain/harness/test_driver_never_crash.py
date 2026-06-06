"""FM2 never-crash: one bad LLM call (schema-invalid output, or a wall-clock
timeout) must NOT kill the whole run with a traceback. The Driver converts such a
recoverable inference failure into a graceful ESCALATE so the session ends with a
report (ABANDONED) instead of crashing — the aimind funnel: 95% per-call valid still
yields a high session-failure rate if any single failure is terminal."""
import asyncio

import pytest

from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult, StructuredOutputError
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import (
    Cursor, Phase, SessionState, VerdictKind,
)
from poor_code.provider.client import LLMCallTimeout


class _BoomNode:
    name = "planner"
    phase = Phase.PLANNING

    def __init__(self, exc):
        self._exc = exc

    async def run(self, ctx):
        raise self._exc


def _route(node, result, state):
    from poor_code.domain.harness.route import route
    return route(node, result, state)


def _start():
    return SessionState(cursor=Cursor(phase=Phase.PLANNING, current_node="planner"))


@pytest.mark.asyncio
async def test_structured_output_error_does_not_crash_driver():
    reg = NodeRegistry()
    reg.register(_BoomNode(StructuredOutputError("planner", "{bad}", "x: bad")))
    driver = Driver(reg, _route)
    state = await driver.run(_start(), asyncio.Event())  # must not raise
    assert driver.last_escape is not None
    assert driver.last_escape.kind is VerdictKind.ESCALATE


@pytest.mark.asyncio
async def test_call_timeout_does_not_crash_driver():
    reg = NodeRegistry()
    reg.register(_BoomNode(LLMCallTimeout("exceeded 300s budget")))
    driver = Driver(reg, _route)
    state = await driver.run(_start(), asyncio.Event())  # must not raise
    assert driver.last_escape is not None
    assert driver.last_escape.kind is VerdictKind.ESCALATE


@pytest.mark.asyncio
async def test_programming_errors_still_propagate():
    """We only swallow recoverable INFERENCE failures — a real bug (KeyError etc.)
    must still surface, not be masked as an escalation."""
    reg = NodeRegistry()
    reg.register(_BoomNode(KeyError("real bug")))
    with pytest.raises(KeyError):
        await Driver(reg, _route).run(_start(), asyncio.Event())
