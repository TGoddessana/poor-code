"""A question must always render as ONE consistent component (the bordered
QueryWidget card) while it is awaiting an answer — whether or not the model
supplied structured `options`. Previously a free-text `clarify` query (no
options) fell through to a bare `❓ {prompt}` Static line, which read like a
chat message rather than a question card.
"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from poor_code.ui.store import QuerySegment, TurnView
from poor_code.ui.widgets.chat_log import StaticSegment, TurnBlock
from poor_code.ui.widgets.query_widget import QueryWidget


class _MutableState:
    def __init__(self, *, awaiting_input: bool, model: str = "gpt-4o") -> None:
        self.awaiting_input = awaiting_input
        self.model = model


class _Harness(App):
    def __init__(self, turn: TurnView, state: _MutableState) -> None:
        super().__init__()
        self._turn = turn
        self._state = state

    @property
    def app_state(self) -> _MutableState:
        return self._state

    def answer_query(self, answer, chosen_option=None):
        pass

    def compose(self) -> ComposeResult:
        yield TurnBlock(self._turn)


def _turn_with(seg) -> TurnView:
    return TurnView(turn_id="T1", cmd_id="c1", user_text="do x",
                    segments=(seg,), status="running")


@pytest.mark.asyncio
async def test_clarify_without_options_renders_as_query_widget():
    state = _MutableState(awaiting_input=True)
    q = QuerySegment(prompt="why exactly?", options=(), kind="clarify")
    app = _Harness(_turn_with(q), state)
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(TurnBlock)
        # The live, no-options query is a QueryWidget card — not a plain Static line.
        assert len(list(block.query(QueryWidget))) == 1
        # And it must compose cleanly with NO option picker.
        assert list(block.query(OptionList)) == []


@pytest.mark.asyncio
async def test_query_widget_with_no_options_has_no_picker():
    """The widget itself tolerates an empty options tuple: prompt + hint, no
    OptionList, no crash in on_mount."""
    class _Bare(App):
        def answer_query(self, answer, chosen_option=None):
            pass

        def compose(self) -> ComposeResult:
            yield QueryWidget(QuerySegment(prompt="open?", options=(), kind="clarify"))

    app = _Bare()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert list(app.query(OptionList)) == []
        assert len(list(app.query(QueryWidget))) == 1
