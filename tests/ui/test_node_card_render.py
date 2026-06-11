import pytest
from textual.app import App
from textual.reactive import reactive
from textual.widgets import Static

from poor_code.messages import (
    NodeEntered, NodeContextCaptured, NodeThinkingDelta, NodeFinished, TurnConcluded,
    TurnStarted, ToolCallStarted, ToolCallFinished,
)
from poor_code.ui.store import AppState, PromptSubmitted, reduce
from poor_code.ui.widgets.chat_log import ChatLog, DebugBlock, NodeCard, ToolCallEntry


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
        # raw context/thinking is present as collapsed debug payloads by default
        text = " ".join(str(w.render()) for w in app.query(Static))
        assert "debug: context" in text
        assert "debug: thinking" in text
        debug = list(app.query(DebugBlock))[0]
        assert debug
        await pilot.click(debug, offset=(2, 0))
        await pilot.pause()
        assert debug.has_class("expanded")
        assert cards[0].has_class("expanded")
        # "suspended" is an internal lifecycle word — while a question is awaiting,
        # the live question card already signals the wait, so the conclusion line
        # must NOT surface the raw "suspended: awaiting input: …" telemetry.
        assert list(app.query(".turn-conclusion")) == []


@pytest.mark.asyncio
async def test_tool_call_with_bracket_content_does_not_crash_layout():
    """Tool args/results are arbitrary text — a bash command or JSON list that
    contains '[' must not be parsed as Textual content markup. Regression for
    MarkupError raised during layout of the .tool-detail Static."""
    app = _Harness()
    async with app.run_test() as pilot:
        s = reduce(app.app_state, PromptSubmitted(cmd_id="c", user_text="hi"))
        s = reduce(s, TurnStarted(cmd_id="c", turn_id="T"))
        s = reduce(s, ToolCallStarted(
            turn_id="T", tool_call_id="tc1", tool_name="bash",
            args={"command": "grep root /etc/hosts"}))
        # A raw string result is rendered verbatim. '[/etc/hosts]' looks like a
        # Textual closing markup tag with no matching open tag — the parser
        # raises MarkupError during layout (get_content_height -> render).
        s = reduce(s, ToolCallFinished(
            turn_id="T", tool_call_id="tc1", result="no match in [/etc/hosts]"))
        app.app_state = s
        await pilot.pause()
        entry = app.query_one(ToolCallEntry)
        # Force the collapsed detail visible so its height/markup is computed.
        entry.add_class("expanded")
        await pilot.pause()
        detail = entry.query_one(".tool-detail", Static)
        # Height computation drives the markup parse that previously crashed.
        detail._render().get_height(detail.styles, 80)
        rendered = str(detail.render())
        assert "/etc/hosts" in rendered


@pytest.mark.asyncio
async def test_user_answer_with_markup_syntax_does_not_crash_layout():
    """The user's own typed text is echoed as a segment. Typing something like
    '[/regex]' must not be interpreted as a Textual closing tag — that would
    crash the whole app on a layout pass over the user's input."""
    from poor_code.messages import QueryRaised
    from poor_code.ui.store import AnswerSubmitted

    app = _Harness()
    async with app.run_test() as pilot:
        s = reduce(app.app_state, PromptSubmitted(cmd_id="c", user_text="hi"))
        s = reduce(s, TurnStarted(cmd_id="c", turn_id="T"))
        s = reduce(s, NodeEntered(turn_id="T", node="interviewer", phase="interviewing", activity="Asking"))
        s = reduce(s, QueryRaised(turn_id="T", query_id="q1", kind="free", prompt="which file?"))
        s = reduce(s, AnswerSubmitted(turn_id="T", answer="search the [/etc/hosts] file"))
        app.app_state = s
        await pilot.pause()
        bodies = [str(w.render()) for w in app.query(Static)]
        assert any("/etc/hosts" in b for b in bodies)


@pytest.mark.asyncio
async def test_non_suspended_conclusion_still_renders():
    """Other terminal reasons (completed/escalated/error) remain user-visible —
    only 'suspended' is suppressed (the question card replaces it)."""
    app = _Harness()
    async with app.run_test() as pilot:
        s = reduce(app.app_state, PromptSubmitted(cmd_id="c", user_text="hi"))
        s = reduce(s, TurnStarted(cmd_id="c", turn_id="T"))
        s = reduce(s, NodeEntered(turn_id="T", node="reporter", phase="finalizing", activity="Done"))
        s = reduce(s, TurnConcluded(turn_id="T", reason="completed", detail="report (succeeded)"))
        app.app_state = s
        await pilot.pause()
        conclusion = app.query_one(".turn-conclusion", Static)
        assert "completed" in str(conclusion.render())
