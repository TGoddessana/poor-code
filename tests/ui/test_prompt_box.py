from dataclasses import dataclass, field

from textual.widgets import Input, OptionList

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route as harness_route
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.slash.base import Arg, ArgKind, ParsedArgs
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.slash.registry import SlashRegistry
from tests.infra.fakes import (
    FakeContextLoader,
    FakeSettingsLoader,
    FakeSystemPromptComposer,
)
from tests.provider.fakes import FakeLLMClient


def _assembler() -> TurnAssembler:
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(),
        context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(),
        prompt_builder=PromptBuilder(),
    )


@dataclass
class _Cmd:
    name: str
    description: str
    args: tuple = ()
    seen: list[ParsedArgs] = field(default_factory=list)
    def execute(self, ctx, parsed): self.seen.append(parsed)


def _make_driver(_llm):
    return Driver(NodeRegistry(), harness_route)


def _app_with(*cmds) -> PoorCodeApp:
    agent = Agent(
        llm=FakeLLMClient.text_only("nope"),
        tools=ToolRegistry([]),
        assembler=_assembler(),
    )
    slash = SlashDispatcher(SlashRegistry(list(cmds)))
    return PoorCodeApp(agent=agent, make_driver=_make_driver, slash=slash)


async def test_typing_slash_shows_popup_with_all_commands():
    app = _app_with(_Cmd("login", "Sign in"), _Cmd("help", "Show help"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.display is True
        assert suggest.option_count == 2


async def test_typing_filters_by_prefix():
    app = _app_with(_Cmd("login", "Sign in"), _Cmd("help", "Show help"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l", "o")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.option_count == 1


async def test_whitespace_after_name_hides_popup():
    app = _app_with(_Cmd("login", "Sign in"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l", "o", "g", "i", "n", "space")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.display is False


async def test_no_matches_hides_popup():
    app = _app_with(_Cmd("login", "Sign in"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "z", "z", "z")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.display is False


async def test_tab_fills_input_and_hides_popup():
    cmd = _Cmd("login", "Sign in")
    app = _app_with(cmd)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        input_w = pilot.app.screen.query_one(Input)
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert input_w.value == "/login "
        assert suggest.display is False
        assert cmd.seen == []  # Tab does not execute


async def test_enter_on_no_arg_command_executes():
    cmd = _Cmd("login", "Sign in")
    app = _app_with(cmd)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(5):
            await pilot.pause()
        assert len(cmd.seen) == 1
        assert pilot.app.screen.query_one(Input).value == ""


async def test_enter_on_arg_command_fills_without_executing():
    cmd = _Cmd("skill", "Run a skill",
               args=(Arg("name", ArgKind.TOKEN), Arg("prompt", ArgKind.REST, optional=True)))
    app = _app_with(cmd)
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        input_w = pilot.app.screen.query_one(Input)
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert input_w.value == "/skill "
        assert suggest.display is False
        assert cmd.seen == []


async def test_escape_hides_popup_preserves_input():
    app = _app_with(_Cmd("login", "Sign in"))
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("/", "l", "o")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        suggest = pilot.app.screen.query_one("#slash-suggest", OptionList)
        assert suggest.display is False
        assert pilot.app.screen.query_one(Input).value == "/lo"


async def test_enter_while_processing_does_not_clear_input():
    app = _app_with()
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()

        from poor_code.ui.store import PromptSubmitted
        pilot.app.store.dispatch(PromptSubmitted(cmd_id="x", user_text="hello"))
        assert pilot.app.app_state.is_processing is True

        inp = pilot.app.screen.query_one(Input)
        inp.focus()
        inp.value = "new message"
        await pilot.press("enter")
        await pilot.pause()

        # 제출 차단 시 입력값이 그대로 유지됨
        assert inp.value == "new message"


async def test_all_mascot_frames_have_same_width():
    """border-top 흔들림 방지: 모든 프레임이 같은 너비여야 한다."""
    from poor_code.ui.widgets.prompt_box import (
        IDLE_FRAME, PENDING_FRAMES, RUNNING_FRAMES,
    )
    all_frames = [IDLE_FRAME, *PENDING_FRAMES, *RUNNING_FRAMES]
    widths = {len(f) for f in all_frames}
    assert len(widths) == 1, f"frame widths must be uniform, got {widths}: {all_frames}"


async def test_compute_mascot_mode_matrix():
    from poor_code.ui.store import AppState, TextSegment, TurnView
    from poor_code.ui.widgets.prompt_box import compute_mascot_mode

    # idle
    assert compute_mascot_mode(AppState()) == "idle"
    assert compute_mascot_mode(AppState(is_processing=False)) == "idle"

    # pending: processing but no segments yet
    pending = TurnView(turn_id=None, cmd_id="c1", user_text="hi", status="pending")
    assert compute_mascot_mode(AppState(turns=(pending,), is_processing=True)) == "pending"

    # running: processing with segments
    running = TurnView(
        turn_id="T1", cmd_id="c1", user_text="hi",
        segments=(TextSegment(text="a"),), status="running",
    )
    assert compute_mascot_mode(AppState(turns=(running,), is_processing=True)) == "running"


async def test_promptbox_border_title_idle_on_mount():
    from poor_code.ui.widgets.prompt_box import IDLE_FRAME, PromptBox
    app = _app_with()
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        box = pilot.app.screen.query_one(PromptBox)
        assert box.border_title == IDLE_FRAME


async def test_promptbox_border_title_switches_to_pending_when_processing():
    from poor_code.ui.store import PromptSubmitted
    from poor_code.ui.widgets.prompt_box import PENDING_FRAMES, PromptBox
    app = _app_with()
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.store.dispatch(PromptSubmitted(cmd_id="x", user_text="hello"))
        await pilot.pause()
        box = pilot.app.screen.query_one(PromptBox)
        assert box.border_title == PENDING_FRAMES[0]


async def test_promptbox_border_title_returns_to_idle_when_turn_ends():
    from poor_code.messages import TurnEnded, TurnStarted
    from poor_code.ui.store import PromptSubmitted
    from poor_code.ui.widgets.prompt_box import IDLE_FRAME, PromptBox
    app = _app_with()
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.store.dispatch(PromptSubmitted(cmd_id="x", user_text="hi"))
        pilot.app.store.dispatch(TurnStarted(cmd_id="x", turn_id="t1"))
        await pilot.pause()

        pilot.app.store.dispatch(TurnEnded(turn_id="t1", duration_sec=0.0, model=""))
        await pilot.pause()
        box = pilot.app.screen.query_one(PromptBox)
        assert box.border_title == IDLE_FRAME


async def test_placeholder_changes_when_processing():
    app = _app_with()
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()

        inp = pilot.app.screen.query_one(Input)
        original = inp.placeholder

        from poor_code.ui.store import PromptSubmitted
        pilot.app.store.dispatch(PromptSubmitted(cmd_id="x", user_text="hello"))
        await pilot.pause()

        assert inp.placeholder == "Ctrl+C to cancel"

        from poor_code.messages import TurnStarted, TurnEnded
        pilot.app.store.dispatch(TurnStarted(cmd_id="x", turn_id="t1"))
        pilot.app.store.dispatch(TurnEnded(turn_id="t1", duration_sec=0.0, model=""))
        await pilot.pause()

        assert inp.placeholder == original
