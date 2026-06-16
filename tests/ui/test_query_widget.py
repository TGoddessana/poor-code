import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static
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


# --- regression: a destructive rewrite once dropped the prompt text and the
# focus hand-off, so the question body vanished and the picker stayed glued to
# the keyboard after answering. These pin both contracts. ---


@pytest.mark.asyncio
async def test_option_query_renders_prompt_text():
    """The question body must be visible — not just the option picker."""
    seg = QuerySegment(prompt="which path?", options=("A", "B"), kind="choose")
    app = _Harness(seg)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one(".query-prompt", Static)
        assert "which path?" in str(prompt.render())


@pytest.mark.asyncio
async def test_clarify_query_renders_prompt_text():
    """Free-text (no options) clarify questions must still show the question."""
    seg = QuerySegment(prompt="why exactly?", options=(), kind="clarify")
    app = _Harness(seg)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one(".query-prompt", Static)
        assert "why exactly?" in str(prompt.render())


@pytest.mark.asyncio
async def test_focus_returns_to_prompt_input_on_unmount():
    """When the picker is dismissed it must hand the keyboard back to the
    prompt box, so the next keypress (steering / next answer) lands there."""
    seg = QuerySegment(prompt="which?", options=("A", "B"), kind="choose")

    class _FocusHarness(App):
        def answer_query(self, answer, chosen_option=None):
            pass

        def compose(self) -> ComposeResult:
            yield QueryWidget(seg)
            yield Input(id="prompt-input")

    app = _FocusHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(QueryWidget)
        await widget.remove()
        await pilot.pause()
        assert app.focused is app.query_one("#prompt-input", Input)


@pytest.mark.asyncio
async def test_context_and_rationale_render_as_separate_regions():
    seg = QuerySegment(prompt="which path?", options=("A", "B"), kind="choose",
                       context="only one entrypoint exists", rationale="decides build target")
    app = _Harness(seg)
    async with app.run_test() as pilot:
        await pilot.pause()
        ctx = app.query_one(".query-context", Static)
        why = app.query_one(".query-rationale", Static)
        assert "only one entrypoint exists" in str(ctx.render())
        assert "decides build target" in str(why.render())


@pytest.mark.asyncio
async def test_absent_context_and_rationale_render_no_region():
    seg = QuerySegment(prompt="which path?", options=("A", "B"), kind="choose")
    app = _Harness(seg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.query(".query-context")) == 0
        assert len(app.query(".query-rationale")) == 0


@pytest.mark.asyncio
async def test_chip_uses_kind_and_resolves_as_border_title():
    seg = QuerySegment(prompt="which?", options=("A",), kind="clarify", resolves="req.summary")
    app = _Harness(seg)
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(QueryWidget)
        assert "clarify" in str(widget.border_title)
        assert "req.summary" in str(widget.border_title)
