import pytest
from textual.app import App, ComposeResult
from poor_code.ui.store import QuerySegment
from poor_code.ui.widgets.query_widget import QueryWidget


class _Harness(App):
    def __init__(self, seg):
        super().__init__()
        self.seg = seg
        self.answered = None

    def answer_query(self, answer, chosen_option=None):
        self.answered = (answer, chosen_option)

    def compose(self) -> ComposeResult:
        yield QueryWidget(self.seg)


@pytest.mark.asyncio
async def test_enter_selects_highlighted_option():
    seg = QuerySegment(prompt="which?", options=("A", "B", "C"), kind="choose")
    app = _Harness(seg)
    async with app.run_test() as pilot:
        await pilot.press("down")   # move to B
        await pilot.press("enter")
        assert app.answered == ("B", "B")


@pytest.mark.asyncio
async def test_first_option_is_default_selection():
    seg = QuerySegment(prompt="which?", options=("A", "B"), kind="approve")
    app = _Harness(seg)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert app.answered == ("A", "A")
