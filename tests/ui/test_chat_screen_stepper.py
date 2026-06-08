import pytest
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
from poor_code.ui.widgets.stepper import StepperBar
from poor_code.ui.screens.state_inspector import StateInspector
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
    name = "router"

    async def run(self, ctx):
        return NodeResult(
            output=Request(raw_text=ctx.state.request.raw_text, kind=RequestKind.ENGINEERING)
        )


def _make_driver_factory():
    def make(_llm, _on_step=None):
        reg = NodeRegistry()
        reg.register(_RouterEng())
        return Driver(reg, route)

    return make


def _app() -> PoorCodeApp:
    agent = Agent(
        llm=FakeLLMClient.text_only("x"),
        tools=ToolRegistry([]),
        assembler=_assembler(),
    )
    return PoorCodeApp(agent=agent, make_driver=_make_driver_factory())


@pytest.mark.asyncio
async def test_chat_screen_mounts_stepper():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        # StepperBar should be mounted inside the ChatScreen
        # app.screen is the ChatScreen (pushed in on_mount); query within it
        results = app.screen.query(StepperBar)
        assert len(results) > 0, "StepperBar was not found in the ChatScreen"


@pytest.mark.asyncio
async def test_ctrl_i_opens_state_inspector():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        # State inspector should not be open initially
        assert not isinstance(app.screen, StateInspector)
        # Press ctrl+i to open
        await pilot.press("ctrl+i")
        await pilot.pause()
        assert isinstance(app.screen, StateInspector), (
            "Expected StateInspector to be the current screen after ctrl+i"
        )


@pytest.mark.asyncio
async def test_ctrl_i_toggles_state_inspector():
    app = _app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        # Open inspector
        await pilot.press("ctrl+i")
        await pilot.pause()
        assert isinstance(app.screen, StateInspector)
        # Press ctrl+i again to close (pops the modal)
        await pilot.press("ctrl+i")
        await pilot.pause()
        assert not isinstance(app.screen, StateInspector), (
            "Expected StateInspector to be dismissed after second ctrl+i"
        )
