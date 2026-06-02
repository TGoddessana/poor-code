import asyncio
import pytest

from poor_code.domain.harness.headless import run_headless
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import (
    Cursor, Phase, Query, QueryKind, Report, ReportOutcome, Request, RequestKind,
    SessionState,
)


def _route_forward(node, result, state):
    # minimal route: q_node → reporter; reporter terminal; esc_node parks at "user"
    return {"q_node": "reporter", "esc_node": "user"}.get(node)


class _AskOnceNode:
    name = "q_node"
    def __init__(self): self._asked = False
    async def run(self, ctx):
        if not self._asked:
            self._asked = True
            return NodeResult(query=Query(id="q1", kind=QueryKind.CLARIFY, prompt="scope?"))
        return NodeResult()


class _ReporterNode:
    name = "reporter"
    async def run(self, ctx):
        from poor_code.domain.harness.nodes.reporter import build_report
        return NodeResult(output=build_report(ctx.state, ReportOutcome.SUCCEEDED))


class _EscalateNode:
    name = "esc_node"
    async def run(self, ctx):
        from poor_code.domain.session.models import Verdict, VerdictKind
        return NodeResult(verdict=Verdict(kind=VerdictKind.ESCALATE, query="stuck"))


def _state(node: str) -> SessionState:
    return SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node=node),
        request=Request(raw_text="do it", kind=RequestKind.ENGINEERING))


@pytest.mark.asyncio
async def test_full_auto_auto_answers_query_then_reaches_report():
    from poor_code.domain.harness.driver import Driver
    reg = NodeRegistry(); reg.register(_AskOnceNode()); reg.register(_ReporterNode())
    driver = Driver(reg, _route_forward)
    final = await run_headless(driver, _state("q_node"), asyncio.Event(), sink=None)
    assert isinstance(final.report, Report)
    assert final.report.outcome is ReportOutcome.SUCCEEDED


@pytest.mark.asyncio
async def test_full_auto_escalate_parks_at_user_and_stamps_abandoned():
    from poor_code.domain.harness.driver import Driver
    reg = NodeRegistry(); reg.register(_EscalateNode())  # "user" unregistered → park
    driver = Driver(reg, _route_forward)
    final = await run_headless(driver, _state("esc_node"), asyncio.Event(), sink=None)
    assert final.report is not None
    assert final.report.outcome is ReportOutcome.ABANDONED
