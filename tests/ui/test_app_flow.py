import asyncio
from dataclasses import dataclass, field

from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
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


async def test_submit_routes_through_agent_and_updates_store():
    async with PoorCodeApp(agent=_agent_text("hi there")).run_test() as pilot:
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
        assert turn.assistant_text == "hi there"
        assert state.is_processing is False


async def test_cancel_during_turn_marks_failed():
    """Build a FakeLLMClient that yields slowly so we can cancel mid-stream."""

    class _SlowLLM:
        async def stream(self, messages, tools):
            for _ in range(50):
                await asyncio.sleep(0.05)
                yield TextDelta(text=".")
            yield FinishedReason(reason="stop")

    agent = Agent(llm=_SlowLLM(), tools=ToolRegistry([]), assembler=_default_assembler())
    async with PoorCodeApp(agent=agent).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(delay=0.05)
        assert pilot.app.store.state.is_processing is True
        pilot.app.action_cancel_or_quit()
        for _ in range(20):
            await pilot.pause(delay=0.05)
        state = pilot.app.store.state
        assert state.is_processing is False
        assert state.turns[0].status == "failed"
        assert state.last_error == "cancelled"


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
    app = PoorCodeApp(agent=_agent_text("should-not-run"), slash=slash)
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
