"""Integration: a driven turn writes a per-turn observability trace under the
session dir, and the drive's termination reason is recorded."""
import json
import pytest
from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route
from poor_code.domain.session import SessionService
from poor_code.domain.session.models import Request, RequestKind
from poor_code.domain.session.store import SessionStore
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra import paths
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from tests.infra.fakes import (
    FakeContextLoader, FakeSettingsLoader, FakeSystemPromptComposer,
)
from tests.provider.fakes import FakeLLMClient


def _assembler() -> TurnAssembler:
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(), context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(), prompt_builder=PromptBuilder())


class _RouterEng:
    name = "router"
    async def run(self, ctx):
        return NodeResult(output=Request(raw_text=ctx.state.request.raw_text,
                                         kind=RequestKind.ENGINEERING))


def _make_driver_factory():
    def make(_llm, _on_step=None):
        reg = NodeRegistry()
        reg.register(_RouterEng())
        return Driver(reg, route)   # router → "explorer" (unregistered) → park
    return make


@pytest.mark.asyncio
async def test_turn_writes_trace_jsonl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = paths.config_dir(tmp_path)
    session = SessionService(SessionStore(root))
    session.start_session(tmp_path)

    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=_assembler())
    app = PoorCodeApp(agent=agent, make_driver=_make_driver_factory(), session=session)

    async with app.run_test() as pilot:
        app.submit("do x")
        for _ in range(40):
            await pilot.pause()

    traces = list((root / "sessions").glob("*/turns/*/trace.jsonl"))
    assert len(traces) == 1, f"expected one trace file, got {traces}"
    recs = [json.loads(l) for l in traces[0].read_text().splitlines()]
    types = [r["type"] for r in recs]
    assert "node_entered" in types
    assert "node_finished" in types
    concluded = next(r for r in recs if r["type"] == "turn_concluded")
    # the graph parked at an unreached node — exactly the "silent stop" that issue #5
    # asked to make observable; the reason + which node is now recorded.
    assert concluded["reason"] == "parked" and "not reached" in concluded["detail"]
