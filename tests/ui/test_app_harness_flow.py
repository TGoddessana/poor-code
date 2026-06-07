import asyncio
import pytest
from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import Request, RequestKind
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from tests.infra.fakes import (
    FakeContextLoader, FakeSettingsLoader, FakeSystemPromptComposer,
)
from tests.provider.fakes import FakeLLMClient


def _assembler() -> TurnAssembler:
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(),
        context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(),
        prompt_builder=PromptBuilder(),
    )


class _RouterEng:
    """Router that always classifies engineering, then parks (route → unregistered)."""
    name = "router"
    async def run(self, ctx):
        return NodeResult(output=Request(raw_text=ctx.state.request.raw_text,
                                         kind=RequestKind.ENGINEERING))


def _make_driver_factory():
    def make(_llm):
        reg = NodeRegistry()
        reg.register(_RouterEng())
        return Driver(reg, route)   # router → "explorer" (unregistered) → park
    return make


def _app() -> PoorCodeApp:
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=_assembler())
    return PoorCodeApp(agent=agent, make_driver=_make_driver_factory())


def test_app_holds_static_narrator():
    from poor_code.ui.narrator import StaticNarrator
    app = _app()
    assert isinstance(app._narrator, StaticNarrator)


@pytest.mark.asyncio
async def test_engineering_request_runs_through_driver_and_ends():
    async with _app().run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("f", "i", "x")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()
        state = pilot.app.store.state
        assert len(state.turns) == 1
        assert state.turns[0].user_text == "fix"
        assert state.turns[0].status == "done"
        assert state.is_processing is False
        # no-plan/no-query terminal park clears the parked state
        assert pilot.app._harness_state is None
