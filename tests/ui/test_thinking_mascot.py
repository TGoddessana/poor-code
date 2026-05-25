"""ThinkingMascot은 글로벌 위젯. app.app_state를 watch하여 모드 자체 결정."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from poor_code.ui.store import AppState, TextSegment, ToolCallView, TurnView
from poor_code.ui.widgets.mascot import ThinkingMascot


class _Host(App):
    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def compose(self) -> ComposeResult:
        yield ThinkingMascot()

    def push(self, state: AppState) -> None:
        self.app_state = state


def _frame(mascot: ThinkingMascot) -> str:
    return str(mascot.query_one(".mascot-frame", Static).content)


async def test_idle_mode_when_not_processing():
    async with _Host().run_test() as pilot:
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        assert mascot._mode == "idle"
        assert _frame(mascot) == ThinkingMascot.IDLE_FRAME


async def test_pending_mode_when_processing_with_no_segments():
    async with _Host().run_test() as pilot:
        await pilot.pause()
        turn = TurnView(turn_id=None, cmd_id="c1", user_text="hi", status="pending")
        pilot.app.push(AppState(turns=(turn,), is_processing=True))
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        assert mascot._mode == "pending"
        assert _frame(mascot) == ThinkingMascot.PENDING_FRAMES[0]


async def test_running_mode_when_processing_with_segments():
    async with _Host().run_test() as pilot:
        await pilot.pause()
        tc = ToolCallView(tool_call_id="t1", tool_name="read", args={"path": "a.py"}, status="running")
        turn = TurnView(
            turn_id="T1", cmd_id="c1", user_text="hi",
            segments=(tc,), status="running",
        )
        pilot.app.push(AppState(turns=(turn,), is_processing=True))
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        assert mascot._mode == "running"
        assert _frame(mascot) == ThinkingMascot.RUNNING_FRAMES[0]


async def test_mode_transitions_when_state_changes():
    async with _Host().run_test() as pilot:
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        assert mascot._mode == "idle"

        pending = TurnView(turn_id=None, cmd_id="c1", user_text="hi", status="pending")
        pilot.app.push(AppState(turns=(pending,), is_processing=True))
        await pilot.pause()
        assert mascot._mode == "pending"

        running = TurnView(
            turn_id="T1", cmd_id="c1", user_text="hi",
            segments=(TextSegment(text="a"),), status="running",
        )
        pilot.app.push(AppState(turns=(running,), is_processing=True))
        await pilot.pause()
        assert mascot._mode == "running"

        done = TurnView(
            turn_id="T1", cmd_id="c1", user_text="hi",
            segments=(TextSegment(text="a"),), status="done",
        )
        pilot.app.push(AppState(turns=(done,), is_processing=False))
        await pilot.pause()
        assert mascot._mode == "idle"


async def test_pending_tick_advances_frame():
    async with _Host().run_test() as pilot:
        await pilot.pause()
        turn = TurnView(turn_id=None, cmd_id="c1", user_text="hi", status="pending")
        pilot.app.push(AppState(turns=(turn,), is_processing=True))
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        mascot._tick()
        await pilot.pause()
        assert _frame(mascot) == ThinkingMascot.PENDING_FRAMES[1]


async def test_running_tick_advances_frame():
    async with _Host().run_test() as pilot:
        await pilot.pause()
        turn = TurnView(
            turn_id="T1", cmd_id="c1", user_text="hi",
            segments=(TextSegment(text="a"),), status="running",
        )
        pilot.app.push(AppState(turns=(turn,), is_processing=True))
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        assert _frame(mascot) == ThinkingMascot.RUNNING_FRAMES[0]
        mascot._tick()
        await pilot.pause()
        assert _frame(mascot) == ThinkingMascot.RUNNING_FRAMES[1]


async def test_idle_mode_has_no_timer():
    async with _Host().run_test() as pilot:
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        assert mascot._mode == "idle"
        assert mascot._timer is None


async def test_running_mode_has_timer():
    async with _Host().run_test() as pilot:
        await pilot.pause()
        turn = TurnView(
            turn_id="T1", cmd_id="c1", user_text="hi",
            segments=(TextSegment(text="a"),), status="running",
        )
        pilot.app.push(AppState(turns=(turn,), is_processing=True))
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        assert mascot._timer is not None
