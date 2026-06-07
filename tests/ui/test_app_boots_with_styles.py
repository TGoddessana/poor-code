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
            output=Request(
                raw_text=ctx.state.request.raw_text,
                kind=RequestKind.ENGINEERING,
            )
        )


def _make_driver_factory():
    def make(_llm):
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
async def test_app_boots_and_stylesheet_parses():
    app = _app()
    async with app.run_test():
        from poor_code.ui.widgets.stepper import StepperBar
        from poor_code.ui.widgets.status_footer import StatusFooter

        assert app.screen.query(StepperBar)
        assert app.screen.query(StatusFooter)
