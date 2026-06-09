import asyncio
from dataclasses import dataclass, field

from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route as harness_route
from poor_code.domain.session.models import Request, RequestKind
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.provider.events import FinishedReason, TextDelta
from poor_code.slash.base import ParsedArgs
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.slash.registry import SlashRegistry
from tests.infra.fakes import FakeContextLoader, FakeSettingsLoader, FakeSystemPromptComposer
from tests.provider.fakes import FakeLLMClient


def _default_assembler() -> TurnAssembler:
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(),
        context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(),
        prompt_builder=PromptBuilder(),
    )


def _agent_text(text: str) -> Agent:
    return Agent(
        llm=FakeLLMClient.text_only(text),
        tools=ToolRegistry([]),
        assembler=_default_assembler(),
    )


class _RouterEng:
    name = "router"
    async def run(self, ctx):
        return NodeResult(output=Request(
            raw_text=ctx.state.request.raw_text, kind=RequestKind.ENGINEERING))


def _make_driver(_llm, _on_step=None):
    reg = NodeRegistry()
    reg.register(_RouterEng())
    return Driver(reg, harness_route)


async def test_submit_routes_through_driver_and_opens_turn():
    app = PoorCodeApp(agent=_agent_text("hi there"), make_driver=_make_driver)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("p", "i", "n", "g")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()

        state = pilot.app.store.state
        assert len(state.turns) == 1
        turn = state.turns[0]
        assert turn.user_text == "ping"
        assert turn.status == "done"
        assert state.is_processing is False


async def test_cancel_during_turn_marks_failed():
    """A node that hangs until cancelled, so we can cancel mid-run."""

    class _Hang:
        name = "router"
        async def run(self, ctx):
            for _ in range(50):
                if ctx.cancel.is_set():
                    raise asyncio.CancelledError("router cancelled")
                await asyncio.sleep(0.05)
            return NodeResult(output=Request(raw_text="x", kind=RequestKind.ENGINEERING))

    def _hang_driver(_llm, _on_step=None):
        reg = NodeRegistry()
        reg.register(_Hang())
        return Driver(reg, harness_route)

    app = PoorCodeApp(agent=_agent_text("x"), make_driver=_hang_driver)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(delay=0.05)
        assert pilot.app.store.state.is_processing is True
        pilot.app.action_interrupt()  # Esc: immediate interrupt of the running turn
        for _ in range(20):
            await pilot.pause(delay=0.05)
        state = pilot.app.store.state
        assert state.is_processing is False
        # Interrupt is human-in-the-loop pause, not a failure: the turn parks in
        # "paused" and the graph checkpoint is preserved for follow-up steering.
        assert state.turns[0].status == "paused"
        assert pilot.app._interrupted is True
        assert pilot.app._harness_state is not None


@dataclass
class _CallCounter:
    name: str = "ping"
    description: str = "test"
    args: tuple = ()
    seen: list[ParsedArgs] = field(default_factory=list)

    def execute(self, ctx, parsed): self.seen.append(parsed)


async def test_submit_slash_routes_through_dispatcher_not_agent():
    cmd = _CallCounter()
    slash = SlashDispatcher(SlashRegistry([cmd]))
    app = PoorCodeApp(agent=_agent_text("should-not-run"), make_driver=_make_driver, slash=slash)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "p", "i", "n", "g")
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()

        assert len(cmd.seen) == 1
        assert cmd.seen[0].values == {}
        # No agent turn should have started.
        assert len(pilot.app.store.state.turns) == 0


from poor_code.provider.providers import ollama_cloud


async def test_on_mount_dispatches_provider_for_llmclient():
    agent = Agent(
        llm=ollama_cloud.configure(model="gpt-oss:120b", api_key="k"),
        tools=ToolRegistry([]),
        assembler=_default_assembler(),
    )
    async with PoorCodeApp(agent=agent, make_driver=_make_driver).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        state = pilot.app.store.state
        assert state.provider_name == "ollama cloud"
        assert state.model == "gpt-oss:120b"


async def test_on_mount_dispatches_none_for_non_llmclient():
    async with PoorCodeApp(agent=_agent_text("x"), make_driver=_make_driver).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        state = pilot.app.store.state
        assert state.provider_name is None
        assert state.model is None


async def test_set_llm_dispatches_new_provider_and_model():
    async with PoorCodeApp(agent=_agent_text("x"), make_driver=_make_driver).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        new_llm = ollama_cloud.configure(model="gpt-oss:20b", api_key="k2")
        pilot.app.set_llm(new_llm)
        await pilot.pause()
        state = pilot.app.store.state
        assert state.provider_name == "ollama cloud"
        assert state.model == "gpt-oss:20b"
