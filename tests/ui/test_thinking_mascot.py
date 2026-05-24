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
