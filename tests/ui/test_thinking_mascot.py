import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from poor_code.ui.widgets.chat_log import ThinkingMascot


class _App(App):
    def compose(self) -> ComposeResult:
        yield ThinkingMascot("pending")


class _RunningApp(App):
    def compose(self) -> ComposeResult:
        yield ThinkingMascot("running")


async def test_pending_initial_frame():
    async with _App().run_test() as pilot:
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        text = mascot.query_one(".mascot-frame", Static).content
        assert text == ThinkingMascot.PENDING_FRAMES[0]


async def test_pending_tick_advances_frame():
    async with _App().run_test() as pilot:
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        mascot._tick()
        await pilot.pause()
        text = mascot.query_one(".mascot-frame", Static).content
        assert text == ThinkingMascot.PENDING_FRAMES[1]


async def test_pending_tick_wraps_around():
    async with _App().run_test() as pilot:
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        for _ in range(len(ThinkingMascot.PENDING_FRAMES)):
            mascot._tick()
        await pilot.pause()
        text = mascot.query_one(".mascot-frame", Static).content
        assert text == ThinkingMascot.PENDING_FRAMES[0]


async def test_running_uses_running_frames():
    async with _RunningApp().run_test() as pilot:
        await pilot.pause()
        mascot = pilot.app.query_one(ThinkingMascot)
        text = mascot.query_one(".mascot-frame", Static).content
        assert text == ThinkingMascot.RUNNING_FRAMES[0]
        mascot._tick()
        await pilot.pause()
        text2 = mascot.query_one(".mascot-frame", Static).content
        assert text2 == ThinkingMascot.RUNNING_FRAMES[1]


from poor_code.ui.widgets.chat_log import ToolCallEntry, SPINNER_FRAMES
from poor_code.ui.store import ToolCallView


class _EntryApp(App):
    def compose(self) -> ComposeResult:
        tc = ToolCallView(
            tool_call_id="t1",
            tool_name="bash",
            args={"command": "ls"},
            status="running",
        )
        yield ToolCallEntry(tc)


async def test_spinner_initial_frame_is_first():
    async with _EntryApp().run_test() as pilot:
        await pilot.pause()
        entry = pilot.app.query_one(ToolCallEntry)
        summary = str(entry.query_one(".tool-summary", Static).content)
        assert SPINNER_FRAMES[0] in summary


async def test_spinner_tick_advances_frame():
    async with _EntryApp().run_test() as pilot:
        await pilot.pause()
        entry = pilot.app.query_one(ToolCallEntry)
        entry._tick()
        await pilot.pause()
        summary = str(entry.query_one(".tool-summary", Static).content)
        assert SPINNER_FRAMES[1] in summary


async def test_spinner_tick_wraps():
    async with _EntryApp().run_test() as pilot:
        await pilot.pause()
        entry = pilot.app.query_one(ToolCallEntry)
        for _ in range(len(SPINNER_FRAMES)):
            entry._tick()
        await pilot.pause()
        summary = str(entry.query_one(".tool-summary", Static).content)
        assert SPINNER_FRAMES[0] in summary
