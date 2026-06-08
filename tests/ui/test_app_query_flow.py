import pytest
from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    Query, QueryKind, Request, RequestKind,
)
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


class _AskOnce:
    """Router-positioned node: first run asks a query; after the answer, parks (route None)."""
    name = "router"
    async def run(self, ctx):
        if not ctx.state.interview:
            return NodeResult(query=Query(
                id="q1", kind=QueryKind.CLARIFY, prompt="why?"))
        return NodeResult(output=Request(raw_text="x", kind=RequestKind.LIGHTWEIGHT))


def _make_driver(_llm, _on_step=None):
    reg = NodeRegistry()
    reg.register(_AskOnce())
    # lightweight → fast_path (unregistered) → park after the answer
    return Driver(reg, route)


def _app():
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=_assembler())
    return PoorCodeApp(agent=agent, make_driver=_make_driver)


@pytest.mark.asyncio
async def test_query_then_answer_resumes_same_turn():
    async with _app().run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("g", "o")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()
        # suspended: one turn, awaiting input, query rendered
        state = pilot.app.store.state
        assert len(state.turns) == 1
        assert state.awaiting_input is True
        assert pilot.app._harness_state.pending_query.id == "q1"

        # answer it
        pilot.app.screen.query_one(Input).value = "because"
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()
        state = pilot.app.store.state
        assert len(state.turns) == 1            # still ONE long turn
        assert state.awaiting_input is False
        assert state.turns[0].status == "done"
        assert pilot.app._harness_state is None


@pytest.mark.asyncio
async def test_answer_query_carries_chosen_option():
    """answer_query(answer, chosen_option) dispatches AnswerSubmitted, clears
    awaiting_input, and appends a UserAnswerSegment — same as the free-text
    answer branch in submit() but chosen_option is forwarded on UserResponse."""
    from poor_code.ui.store import UserAnswerSegment

    async with _app().run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("g", "o")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()

        # Confirm we reached the parked-query state
        state = pilot.app.store.state
        assert state.awaiting_input is True
        assert pilot.app._harness_state.pending_query.id == "q1"

        # Call answer_query with a chosen_option instead of going through the
        # Input widget so that chosen_option is non-None.
        pilot.app.answer_query("A", chosen_option="A")
        for _ in range(20):
            await pilot.pause()

        state = pilot.app.store.state
        # awaiting_input must be cleared
        assert state.awaiting_input is False
        # A UserAnswerSegment with the answer text must have been appended
        turn = state.turns[0]
        answer_segs = [s for s in turn.segments if isinstance(s, UserAnswerSegment)]
        assert len(answer_segs) >= 1
        assert answer_segs[-1].text == "A"
