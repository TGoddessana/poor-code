import pytest
from textual.app import App
from textual.reactive import reactive
from textual.widgets import Static

from poor_code.messages import (
    NodeEntered, NodeContextCaptured, NodeThinkingDelta, NodeFinished, TurnConcluded,
    TurnStarted,
)
from poor_code.ui.store import AppState, PromptSubmitted, reduce
from poor_code.ui.widgets.chat_log import ChatLog, NodeCard


class _Harness(App):
    app_state = reactive(AppState())

    def compose(self):
        yield ChatLog()


@pytest.mark.asyncio
async def test_node_card_shows_thinking_and_conclusion():
    app = _Harness()
    async with app.run_test() as pilot:
        s = reduce(app.app_state, PromptSubmitted(cmd_id="c", user_text="hi"))
        s = reduce(s, TurnStarted(cmd_id="c", turn_id="T"))
        s = reduce(s, NodeEntered(turn_id="T", node="interviewer", phase="interviewing", activity="Asking"))
        s = reduce(s, NodeContextCaptured(turn_id="T", node="interviewer", summary="2 msgs", full="RAW"))
        s = reduce(s, NodeThinkingDelta(turn_id="T", node="interviewer", text='{"q":"why"}'))
        s = reduce(s, NodeFinished(turn_id="T", node="interviewer", phase="interviewing", duration_sec=3.2, status="parked"))
        s = reduce(s, TurnConcluded(turn_id="T", reason="suspended", detail="awaiting input: why?"))
        app.app_state = s
        await pilot.pause()
        cards = list(app.query(NodeCard))
        assert cards, "expected at least one NodeCard"
        # the thinking stream rendered inside a card body
        text = " ".join(str(w.render()) for w in app.query(Static))
        assert '{"q":"why"}' in text
        # conclusion line is present
        conclusion = app.query_one(".turn-conclusion", Static)
        assert "suspended" in str(conclusion.render())
