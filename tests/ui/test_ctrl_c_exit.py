import pytest

from poor_code.app import _is_double_tap


def test_double_tap_within_window_is_true():
    assert _is_double_tap(now=10.0, last=9.0, window=2.0) is True


def test_double_tap_outside_window_is_false():
    assert _is_double_tap(now=10.0, last=7.0, window=2.0) is False


def test_double_tap_with_no_prior_press_is_false():
    assert _is_double_tap(now=10.0, last=None, window=2.0) is False


from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from tests.infra.fakes import (
    FakeContextLoader, FakeSettingsLoader, FakeSystemPromptComposer,
)
from tests.provider.fakes import FakeLLMClient


def _app() -> PoorCodeApp:
    assembler = TurnAssembler(
        settings_loader=FakeSettingsLoader(), context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(), prompt_builder=PromptBuilder())
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=assembler)
    return PoorCodeApp(agent=agent,
                       make_driver=lambda _llm, _on=None: Driver(NodeRegistry(), route))


@pytest.mark.asyncio
async def test_single_ctrl_c_does_not_exit():
    async with _app().run_test() as pilot:
        await pilot.pause()
        pilot.app.action_ctrl_c()
        await pilot.pause()
        assert pilot.app.is_running is True
        assert pilot.app._last_ctrl_c is not None
