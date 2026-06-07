"""Integration test for QueryWidget reconciliation in TurnBlock.refresh_from.

Regression: an option-bearing QuerySegment renders as a QueryWidget (a textual
Static subclass, NOT a StaticSegment) while awaiting_input is True. The reconcile
filter used to ignore QueryWidget, so when the user answered (awaiting_input flips
False and a UserAnswerSegment is appended), the live QueryWidget was never removed
(orphaned) and the segment-index→widget mapping for that turn misaligned.

This drives the mount→answer→reconcile lifecycle at the TurnBlock level and asserts:
  - exactly one QueryWidget while interactive,
  - no orphaned QueryWidget after the answer,
  - the mounted segment widgets align 1:1 with the segments.
"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from poor_code.ui.store import QuerySegment, TurnView, UserAnswerSegment
from poor_code.ui.widgets.chat_log import StaticSegment, TurnBlock
from poor_code.ui.widgets.query_widget import QueryWidget


class _MutableState:
    """Minimal stand-in for AppState exposing the attributes TurnBlock reads."""
    def __init__(self, *, awaiting_input: bool, model: str = "gpt-4o") -> None:
        self.awaiting_input = awaiting_input
        self.model = model


class _Harness(App):
    """Hosts a single TurnBlock and exposes a settable app_state."""
    def __init__(self, turn: TurnView, state: _MutableState) -> None:
        super().__init__()
        self._turn = turn
        self._state = state

    @property
    def app_state(self) -> _MutableState:
        return self._state

    def answer_query(self, answer, chosen_option=None):  # QueryWidget calls this
        pass

    def compose(self) -> ComposeResult:
        yield TurnBlock(self._turn)


@pytest.mark.asyncio
async def test_query_widget_reconciles_on_answer():
    state = _MutableState(awaiting_input=True)
    q = QuerySegment(prompt="which?", options=("A", "B"), kind="choose")
    turn = TurnView(
        turn_id="T1", cmd_id="c1", user_text="pick one",
        segments=(q,), status="running",
    )
    app = _Harness(turn, state)
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(TurnBlock)

        # 1. While interactive: exactly one QueryWidget, no read-only StaticSegment
        #    standing in for the query.
        assert len(list(block.query(QueryWidget))) == 1, (
            "expected exactly one live QueryWidget while awaiting_input"
        )

        # 2. User answers: awaiting_input flips False, query echoes as a
        #    UserAnswerSegment, and the turn is reconciled.
        state.awaiting_input = False
        answered_turn = TurnView(
            turn_id="T1", cmd_id="c1", user_text="pick one",
            segments=(q, UserAnswerSegment(text="A")), status="running",
        )
        block.refresh_from(answered_turn)
        for _ in range(3):
            await pilot.pause()

        # 3. No orphaned QueryWidget; segments align 1:1 as StaticSegments.
        queries = list(block.query(QueryWidget))
        statics = list(block.query(StaticSegment))
        assert queries == [], (
            f"orphaned QueryWidget(s) after answer: {len(queries)}"
        )
        assert len(statics) == 2, (
            f"expected 2 StaticSegments (read-only query + user answer), "
            f"got {len(statics)}"
        )
