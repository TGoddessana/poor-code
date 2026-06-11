"""Regression tests for the 4 reported TUI-journey bugs.

1. Stepper bar was invisible — `height: 1` + `border-bottom` collapsed its only
   row, so the rendered text had 0 content rows.
2. Option-query picker: clicking an option committed instantly (unwanted); focus
   onto the picker must be robust so arrow keys work.
3. esc/ctrl+q did nothing — esc had no app binding, and a cancelled/parked turn
   left `awaiting_input` stuck.
"""
import pytest
from textual.widgets import Input, OptionList

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import Query, QueryKind, Request, RequestKind
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.ui.widgets.query_widget import QueryWidget
from poor_code.ui.widgets.stepper import StepperBar
from tests.infra.fakes import (
    FakeContextLoader, FakeSettingsLoader, FakeSystemPromptComposer,
)
from tests.provider.fakes import FakeLLMClient


def _assembler():
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(), context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(), prompt_builder=PromptBuilder())


class _AskOption:
    """Asks ONE option-bearing query, then parks after the answer."""
    name = "router"

    async def run(self, ctx):
        if not ctx.state.interview:
            return NodeResult(query=Query(
                id="q1", kind=QueryKind.CHOOSE, prompt="which footer?",
                options=("bottom bar", "new line", "no UI")))
        return NodeResult(output=Request(raw_text="x", kind=RequestKind.LIGHTWEIGHT))


def _make_driver(_llm, _on_step=None):
    reg = NodeRegistry()
    reg.register(_AskOption())
    return Driver(reg, route)


def _app():
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=_assembler())
    return PoorCodeApp(agent=agent, make_driver=_make_driver)


async def _drive_to_query(pilot):
    app = pilot.app
    await pilot.pause(); await pilot.pause()
    app.screen.query_one(Input).focus()
    await pilot.press("g", "o")
    await pilot.press("enter")
    for _ in range(30):
        await pilot.pause()
    return app


@pytest.mark.asyncio
async def test_stepper_is_visible_once_a_phase_is_active():
    """The stepper must occupy at least one content row (it had height 0)."""
    async with _app().run_test() as pilot:
        app = await _drive_to_query(pilot)
        stepper = app.screen.query_one(StepperBar)
        assert app.store.state.current_phase == "routing"
        assert stepper.display is True
        assert stepper.size.height >= 1, "stepper text collapsed to 0 rows"
        assert "Route" in str(stepper.render())


@pytest.mark.asyncio
async def test_query_keeps_picker_focus_until_answered():
    """While a question is awaiting, the picker OWNS the focus — the prompt box
    must not blink or steal keystrokes. Free-text fallback still works (typing
    is appended to the prompt box's value in the background) but focus never
    leaves the picker until Enter/Esc/option-click resolves the question."""
    async with _app().run_test() as pilot:
        app = await _drive_to_query(pilot)
        prompt = app.screen.query_one(Input)
        picker = app.screen.query_one(QueryWidget).query_one(OptionList)
        assert app.focused is picker
        assert app.focused is not prompt
        assert picker.highlighted == 0


@pytest.mark.asyncio
async def test_click_option_then_enter_commits():
    async with _app().run_test() as pilot:
        app = await _drive_to_query(pilot)
        picker = app.screen.query_one(QueryWidget).query_one(OptionList)
        # Click a specific option (the 2nd: "new line") and then Enter.
        # We pick by index rather than by pixel offset so the test is robust to
        # the option list's visual padding/border.
        picker.highlighted = 1
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()
        state = app.store.state
        from poor_code.ui.store import UserAnswerSegment
        answers = [s for s in state.turns[0].segments
                   if isinstance(s, UserAnswerSegment)]
        assert answers and answers[-1].text == "new line"
        assert state.awaiting_input is False


@pytest.mark.asyncio
async def test_typing_while_query_awaits_keeps_picker_focus_and_swallows_keys():
    """Picker keeps focus throughout (so the prompt box never visually takes
    over or receives stray keystrokes). Typing is consumed by the picker — it
    is NOT forwarded to the prompt box while a question is awaiting, because
    the user explicitly asked that the prompt box not be reachable until Esc.
    """
    async with _app().run_test() as pilot:
        app = await _drive_to_query(pilot)
        prompt = app.screen.query_one(Input)
        picker = app.screen.query_one(QueryWidget).query_one(OptionList)
        assert app.focused is picker

        await pilot.press("c", "u", "s", "t", "o", "m")
        # focus never leaves the picker while the query is awaiting
        assert app.focused is picker
        # prompt box value is untouched — picker swallows letters to keep the
        # user's answer mode unambiguous (Esc is the only way out)
        assert prompt.value == ""


@pytest.mark.asyncio
async def test_escape_on_parked_query_makes_next_input_steering():
    """Esc on a parked query is an intentional HITL intervention.

    The next text should not be recorded as this query's answer; it should resume
    the same cursor with steering so the graph can re-ask/re-route.
    """
    async with _app().run_test() as pilot:
        app = await _drive_to_query(pilot)
        assert app.store.state.awaiting_input is True
        await pilot.press("escape")
        await pilot.pause()
        state = app.store.state
        assert state.awaiting_input is False
        assert state.turns[0].status == "paused"
        # picker dismisses → keyboard should return to the prompt box
        assert isinstance(app.focused, Input), f"expected prompt focused, got {app.focused!r}"
        assert app._interrupted is True
        assert app._harness_state is not None
        assert app._harness_state.pending_query is not None

        await pilot.press("m", "a", "n", "u", "a", "l")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()

        from poor_code.ui.store import UserAnswerSegment
        answers = [s for s in app.store.state.turns[0].segments
                   if isinstance(s, UserAnswerSegment)]
        assert answers and answers[-1].text == "manual"
        assert answers[-1].kind == "steering"
        assert app._harness_state is not None
        assert app._harness_state.interview == ()
        assert app._harness_state.steering_notes == ("manual",)
        assert app.store.state.awaiting_input is True


@pytest.mark.asyncio
async def test_click_highlights_but_does_not_commit():
    """A bare-harness unit check: clicking an option moves the highlight and
    focuses the list, but does NOT answer — only Enter commits."""
    from textual.app import App, ComposeResult
    from poor_code.ui.store import QuerySegment

    class _H(App):
        def __init__(self):
            super().__init__()
            self.answered = None

        def answer_query(self, answer, chosen_option=None):
            self.answered = (answer, chosen_option)

        def compose(self) -> ComposeResult:
            yield QueryWidget(QuerySegment(
                prompt="which?", options=("A", "B", "C"), kind="choose"))

    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ol = app.query_one(OptionList)
        await pilot.click(ol, offset=(2, 1))
        await pilot.pause()
        # The behaviour the user objected to: a click must NOT commit.
        assert app.answered is None, "click must not commit a selection"
        # Clicking the list focuses it so the keyboard takes over.
        assert app.focused is ol
        # Enter is the only commit path.
        await pilot.press("enter")
        await pilot.pause()
        assert app.answered is not None
        assert app.answered[0] in ("A", "B", "C")
