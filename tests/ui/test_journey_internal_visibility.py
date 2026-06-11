"""Tests for issue-4 internal-visibility features:
 • active-node spinner (NodeLabelView animates while the trailing node is still
   working, even after context/thinking/result segments appear),
 • context inspector (render_context surfaces the live SessionState the nodes
   were fed — code context, interview Q&A, requirement).
"""
import pytest
from textual.app import App, ComposeResult

from poor_code.ui.store import (
    NodeLabelSegment, NodeResultSegment, QuerySegment, TurnView,
)
from poor_code.ui.widgets.chat_log import NodeLabelView, TurnBlock
from poor_code.ui.screens.state_inspector import render_context


def _running(*segments) -> TurnView:
    return TurnView(turn_id="t1", cmd_id="c1", user_text="do x",
                    status="running", segments=tuple(segments), started_at=0.0)


class _Host(App):
    def __init__(self, turn):
        super().__init__()
        self.app_state = None
        self._turn = turn

    def compose(self) -> ComposeResult:
        yield TurnBlock(self._turn)


# --- active-node spinner ---

@pytest.mark.asyncio
async def test_trailing_node_label_is_active_while_running():
    turn = _running(NodeLabelSegment(node="interviewer", phase="interviewing",
                                     activity="Asking a clarifying question"))
    app = _Host(turn)
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(TurnBlock)
        block.refresh_from(turn)
        await pilot.pause()
        labels = list(app.query(NodeLabelView))
        assert len(labels) == 1
        assert labels[0]._active is True


@pytest.mark.asyncio
async def test_label_stays_active_while_running_after_a_result_follows():
    seg_label = NodeLabelSegment(node="explorer", phase="locating",
                                 activity="Exploring the codebase")
    app = _Host(_running(seg_label))
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(TurnBlock)
        # A body segment now trails the label, but the node itself is still
        # marked running, so its own timer should keep moving.
        done = _running(seg_label,
                        NodeResultSegment(node="explorer", phase="locating",
                                          headline="Found 3 files"))
        block.refresh_from(done)
        await pilot.pause()
        labels = list(app.query(NodeLabelView))
        assert labels[0]._active is True


@pytest.mark.asyncio
async def test_active_node_label_ticks_its_own_timer_after_body_segments():
    seg_label = NodeLabelSegment(node="explorer", phase="locating",
                                 activity="Exploring the codebase")
    turn = _running(
        seg_label,
        NodeResultSegment(node="explorer", phase="locating", headline="Found 3 files"),
    )
    app = _Host(turn)
    async with app.run_test() as pilot:
        await pilot.pause()
        label = app.query_one(NodeLabelView)
        first = str(label.query_one(".node-label").content)
        label._tick()
        await pilot.pause()
        second = str(label.query_one(".node-label").content)
        assert first != second
        assert "s" in second


@pytest.mark.asyncio
async def test_awaiting_query_does_not_animate_label():
    seg_label = NodeLabelSegment(node="interviewer", phase="interviewing",
                                 activity="Asking a clarifying question",
                                 status="parked")
    app = _Host(_running(seg_label))
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(TurnBlock)
        awaiting = _running(seg_label,
                            QuerySegment(prompt="which?", options=("a", "b"), kind="choose"))
        block.refresh_from(awaiting)
        await pilot.pause()
        labels = list(app.query(NodeLabelView))
        assert labels[0]._active is False


# --- context inspector ---

def test_render_context_empty_when_no_session():
    assert render_context(None) == ""


def test_render_context_surfaces_code_context_and_interview():
    from poor_code.domain.session.models import (
        AnsweredQuery, CodeContext, CodeRef, GroundingStatus, Query, QueryKind,
        SessionState, UserResponse,
    )
    cc = CodeContext(
        candidates=(CodeRef(file="app.py", symbol="submit", lineno=12),),
        summary="adds a slash command",
        grounding=GroundingStatus.NOT_FOUND,
    )
    aq = AnsweredQuery(
        query=Query(id="q1", kind=QueryKind.CHOOSE, prompt="which footer?",
                    options=("bottom", "new line")),
        response=UserResponse(query_id="q1", answer="bottom", chosen_option="bottom"),
    )
    session = SessionState(understanding=cc, interview=(aq,))
    out = render_context(session)
    assert "CODE CONTEXT" in out
    assert "app.py::submit:12" in out
    assert "adds a slash command" in out
    assert "INTERVIEW" in out
    assert "which footer?" in out
    assert "[bottom] bottom" in out
