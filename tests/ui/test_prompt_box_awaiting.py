import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from poor_code.ui.store import AppState
from poor_code.ui.widgets.prompt_box import PromptBox


class _Host(App):
    app_state = AppState()
    slash = None

    def __init__(self):
        super().__init__()
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptBox()

    def submit(self, text):
        self.submitted.append(text)


@pytest.mark.asyncio
async def test_submit_allowed_when_awaiting_even_if_processing():
    app = _Host()
    async with app.run_test() as pilot:
        app.app_state = AppState(is_processing=True, awaiting_input=True)
        await pilot.pause()
        inp = app.query_one(Input)
        inp.focus()
        inp.value = "my answer"
        await pilot.press("enter")
        await pilot.pause()
        assert app.submitted == ["my answer"]


@pytest.mark.asyncio
async def test_submit_blocked_when_processing_and_not_awaiting():
    app = _Host()
    async with app.run_test() as pilot:
        app.app_state = AppState(is_processing=True, awaiting_input=False)
        await pilot.pause()
        inp = app.query_one(Input)
        inp.focus()
        inp.value = "nope"
        await pilot.press("enter")
        await pilot.pause()
        assert app.submitted == []
