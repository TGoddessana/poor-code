import pytest
from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route as harness_route
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from tests.infra.fakes import (
    FakeContextLoader, FakeSettingsLoader, FakeSystemPromptComposer,
)
from tests.provider.fakes import FakeLLMClient


def _assembler():
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(), context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(), prompt_builder=PromptBuilder())


class _Boom:
    name = "router"
    async def run(self, ctx):
        raise RuntimeError("simulated provider 400")


def _make_driver(_llm, _on_step=None):
    reg = NodeRegistry()
    reg.register(_Boom())
    return Driver(reg, harness_route)


@pytest.mark.asyncio
async def test_llm_error_becomes_failed_turn_not_crash():
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=_assembler())
    app = PoorCodeApp(agent=agent, make_driver=_make_driver)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("g", "o")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()
        state = pilot.app.store.state
        assert state.turns[0].status == "failed"
        assert "RuntimeError" in (state.last_error or "")
        assert state.is_processing is False
        assert pilot.app._harness_state is None
