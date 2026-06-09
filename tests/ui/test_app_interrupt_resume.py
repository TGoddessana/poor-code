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


class _BlockingRouter:
    """Hangs forever inside the node — simulates a long in-flight LLM call, so an
    Esc interrupt must cancel the worker rather than wait for a node boundary."""
    name = "router"

    def __init__(self):
        self.entered = asyncio.Event()

    async def run(self, ctx):
        self.entered.set()
        await asyncio.sleep(3600)  # never returns on its own
        return NodeResult(output=Request(
            raw_text=ctx.state.request.raw_text, kind=RequestKind.ENGINEERING))


def _make_app():
    router = _BlockingRouter()

    def make(_llm, _on_step=None):
        reg = NodeRegistry()
        reg.register(router)
        return Driver(reg, route, on_step=_on_step)

    assembler = TurnAssembler(
        settings_loader=FakeSettingsLoader(), context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(), prompt_builder=PromptBuilder())
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=assembler)
    return PoorCodeApp(agent=agent, make_driver=make), router


@pytest.mark.asyncio
async def test_escape_interrupts_in_flight_node_and_preserves_state():
    app, router = _make_app()
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("f", "i", "x")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause()
            if router.entered.is_set():
                break
        assert router.entered.is_set()
        await pilot.press("escape")
        for _ in range(20):
            await pilot.pause()
        st = pilot.app.store.state
        assert st.is_processing is False
        assert st.turns[0].status == "paused"
        assert pilot.app._harness_state is not None     # preserved, NOT discarded
        assert pilot.app._interrupted is True
        assert pilot.app._harness_state.cursor.current_node == "router"


class _OneShotRouter:
    """Records the steering it sees, then parks (route → unregistered 'explorer')."""
    name = "router"

    def __init__(self):
        self.seen_steering = None
        self.entered = asyncio.Event()
        self._block = True

    async def run(self, ctx):
        self.entered.set()
        if self._block:
            await asyncio.sleep(3600)      # first pass: hang for interrupt
        self.seen_steering = ctx.state.steering_notes
        return NodeResult(output=Request(
            raw_text=ctx.state.request.raw_text, kind=RequestKind.ENGINEERING))


@pytest.mark.asyncio
async def test_followup_message_resumes_same_node_with_steering():
    router = _OneShotRouter()

    def make(_llm, _on_step=None):
        reg = NodeRegistry()
        reg.register(router)
        return Driver(reg, route, on_step=_on_step)

    assembler = TurnAssembler(
        settings_loader=FakeSettingsLoader(), context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(), prompt_builder=PromptBuilder())
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=assembler)
    app = PoorCodeApp(agent=agent, make_driver=make)

    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("f", "i", "x")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause()
            if router.entered.is_set():
                break
        assert router.entered.is_set(), "router never entered"
        await pilot.press("escape")
        for _ in range(20):
            await pilot.pause()
        assert pilot.app._interrupted is True   # interrupted, awaiting steering
        turn_id_before = pilot.app._turn_id
        # second message = steering; let the node proceed this time
        router._block = False
        router.entered.clear()
        for ch in "use auth.py":
            await pilot.press(ch if ch != " " else "space")
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
        # same turn (not a new router-from-scratch turn)
        assert pilot.app._turn_id == turn_id_before
        assert len(pilot.app.store.state.turns) == 1
        # the node re-ran and saw the steering note
        assert router.seen_steering == ("use auth.py",)
        assert pilot.app._interrupted is False
