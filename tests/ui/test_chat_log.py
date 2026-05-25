"""Render-side tests for ChatLog / TurnBlock.

These exercise the bugs reported in the rendering hand-off:
  - TurnBlock must shrink to its content (otherwise scroll_end lands in
    empty padding and the user sees nothing).
  - Submitting a new turn must NOT overwrite the previous turn's block
    with the new turn's data.
  - ThinkingMascot must sit at the bottom of the *last* turn (never on
    a previous one) and must not appear wedged between tool entries.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static

from poor_code.ui.store import AppState, TextSegment, ToolCallView, TurnView
from poor_code.ui.widgets.chat_log import (
    ChatLog,
    SPINNER_FRAMES,
    ToolCallEntry,
    TurnBlock,
)
from poor_code.ui.widgets.mascot import ThinkingMascot
from poor_code.ui.widgets.streaming_markdown import StreamingMarkdown


class _Host(App):
    """Minimal app that hosts ChatLog and lets us push AppState directly."""

    from textual.reactive import reactive

    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def compose(self) -> ComposeResult:
        yield ChatLog(id="chat-log")

    def push(self, state: AppState) -> None:
        self.app_state = state


def _done_turn(turn_id: str, user_text: str, *, with_tool: bool = True) -> TurnView:
    segs: tuple = ()
    if with_tool:
        segs = (
            ToolCallView(
                tool_call_id="tc-" + turn_id,
                tool_name="read",
                args={"path": "foo.py"},
                status="done",
                result="x",
            ),
            TextSegment(text="some answer"),
        )
    else:
        segs = (TextSegment(text="some answer"),)
    return TurnView(
        turn_id=turn_id,
        cmd_id="c-" + turn_id,
        user_text=user_text,
        segments=segs,
        status="done",
    )


def _pending_turn(turn_id: str | None, cmd_id: str, user_text: str) -> TurnView:
    return TurnView(
        turn_id=turn_id, cmd_id=cmd_id, user_text=user_text, status="pending"
    )


def _running_turn(
    turn_id: str,
    cmd_id: str,
    user_text: str,
    *,
    text: str = "",
    tools: tuple[ToolCallView, ...] = (),
) -> TurnView:
    segs: tuple = tuple(tools)
    if text:
        segs = segs + (TextSegment(text=text),)
    return TurnView(
        turn_id=turn_id, cmd_id=cmd_id, user_text=user_text,
        segments=segs, status="running",
    )


# -------------------------------------------------------------------------
# TurnBlock layout
# -------------------------------------------------------------------------


async def test_chat_scroll_container_is_anchored_on_mount():
    """The VerticalScroll should be anchored so new turns auto-follow the
    bottom (Textual v4.0.0+ semantics)."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        scroll = pilot.app.query_one("#chat-scroll", VerticalScroll)
        assert scroll.is_anchored


async def test_chat_log_streams_text_deltas_via_append():
    """Pushing successively-longer TextSegment states must update the
    StreamingMarkdown source without remounting the widget. We assert
    widget identity is stable across deltas (block list growing, not
    being replaced) and the final source matches."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        pilot.app.push(AppState(turns=(
            _running_turn("T1", "c1", "hi?", text="Hel"),
        )))
        for _ in range(3):
            await pilot.pause()
        md = pilot.app.query_one(StreamingMarkdown)
        md_id = id(md)

        for accumulated in ("Hello", "Hello world", "Hello world!"):
            pilot.app.push(AppState(turns=(
                _running_turn("T1", "c1", "hi?", text=accumulated),
            )))
            for _ in range(3):
                await pilot.pause()

        md_now = pilot.app.query_one(StreamingMarkdown)
        assert id(md_now) == md_id, "streaming should not remount the widget"
        await md_now.stop_stream()
        for _ in range(3):
            await pilot.pause()
        assert md_now.source == "Hello world!"


async def test_turn_block_uses_streaming_markdown_for_text_segments():
    """Text segments must mount StreamingMarkdown — vanilla Markdown loses
    the append-streaming fast path."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        pilot.app.push(AppState(turns=(_done_turn("T1", "hi", with_tool=False),)))
        for _ in range(5):
            await pilot.pause()
        assert pilot.app.query_one(TurnBlock).query_one(StreamingMarkdown)


async def test_turn_block_height_shrinks_to_content():
    """Without `height: auto` each TurnBlock fills the viewport, so
    scroll_end lands inside an empty 24-row pad and the user sees nothing."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        pilot.app.push(AppState(turns=(_done_turn("T1", "hi"),)))
        for _ in range(5):
            await pilot.pause()
        tb = pilot.app.query_one(TurnBlock)
        # Content is ~3 lines (user msg + answer + one tool). Even with
        # generous markdown wrapping it should stay well under the viewport.
        assert tb.size.height < 12, (
            f"TurnBlock expanded to fill its parent ({tb.size.height} rows); "
            "needs height: auto"
        )


# -------------------------------------------------------------------------
# _sync_turns: new turn must NOT overwrite previous block
# -------------------------------------------------------------------------


async def test_new_turn_preserves_previous_block_content():
    """Submitting turn 2 must keep turn 1's user_text + tool calls intact."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        t1 = _done_turn("T1", "first prompt", with_tool=True)
        pilot.app.push(AppState(turns=(t1,)))
        for _ in range(5):
            await pilot.pause()

        # User submits second prompt → second TurnView appears (pending).
        t2 = _pending_turn(turn_id=None, cmd_id="c2", user_text="second prompt")
        pilot.app.push(AppState(turns=(t1, t2), is_processing=True))
        for _ in range(5):
            await pilot.pause()

        blocks = list(pilot.app.query(TurnBlock))
        assert len(blocks) == 2, f"expected 2 blocks, got {len(blocks)}"

        # Block #0 (first turn) must still show "first prompt", not "second".
        first_user = blocks[0].query_one(".user-msg", Static)
        assert "first prompt" in str(first_user.content)
        assert "second prompt" not in str(first_user.content)

        # And the first turn's tool call should still be there.
        first_tools = list(blocks[0].query(ToolCallEntry))
        assert len(first_tools) == 1, (
            "first turn's tool call was wiped by the new turn"
        )


# -------------------------------------------------------------------------
# Mascot positioning
# -------------------------------------------------------------------------


async def test_mascot_lives_on_last_turn_not_previous():
    """When a second turn starts running, the mascot must be on block 2,
    not pinned to block 1."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        t1 = _done_turn("T1", "first", with_tool=True)
        pilot.app.push(AppState(turns=(t1,)))
        for _ in range(5):
            await pilot.pause()

        t2 = _running_turn("T2", "c2", "second")
        pilot.app.push(AppState(turns=(t1, t2), is_processing=True))
        for _ in range(5):
            await pilot.pause()

        blocks = list(pilot.app.query(TurnBlock))
        first_mascots = list(blocks[0].query(ThinkingMascot))
        last_mascots = list(blocks[-1].query(ThinkingMascot))
        assert first_mascots == [], "mascot must not appear on a finished turn"
        assert last_mascots, "mascot missing from the active (last) turn"


async def test_mascot_sits_after_tool_calls_not_between_them():
    """When tool calls arrive while the mascot is mounted, the mascot
    must stay at the bottom of the block, never sandwiched between two
    tool entries."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        # Begin a running turn with one tool already in flight.
        tc1 = ToolCallView(
            tool_call_id="tc1", tool_name="read",
            args={"path": "a.py"}, status="done",
        )
        s1 = AppState(
            turns=(_running_turn("T1", "c1", "hi", tools=(tc1,)),),
            is_processing=True,
        )
        pilot.app.push(s1)
        for _ in range(5):
            await pilot.pause()

        # A second tool starts. The mascot was already mounted from s1.
        tc2 = ToolCallView(
            tool_call_id="tc2", tool_name="read",
            args={"path": "b.py"}, status="running",
        )
        s2 = AppState(
            turns=(_running_turn("T1", "c1", "hi", tools=(tc1, tc2)),),
            is_processing=True,
        )
        pilot.app.push(s2)
        for _ in range(5):
            await pilot.pause()

        block = pilot.app.query_one(TurnBlock)
        children = list(block.children)
        tool_indices = [i for i, c in enumerate(children) if isinstance(c, ToolCallEntry)]
        mascot_indices = [i for i, c in enumerate(children) if isinstance(c, ThinkingMascot)]
        assert tool_indices and mascot_indices
        assert max(tool_indices) < min(mascot_indices), (
            f"mascot got sandwiched between tools: order={[type(c).__name__ for c in children]}"
        )


# -------------------------------------------------------------------------
# Assistant text rendering
# -------------------------------------------------------------------------


async def test_assistant_text_renders_after_tools_in_streaming():
    """After tool calls, when the model streams its final answer, the
    Markdown widget must end up in the DOM (this is the surface the
    iter-2-doesn't-show bug manifests on)."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        tc1 = ToolCallView(
            tool_call_id="tc1", tool_name="read",
            args={"path": "x.py"}, status="done",
        )
        # Tools have finished, no text yet.
        pilot.app.push(AppState(
            turns=(_running_turn("T1", "c1", "hi", tools=(tc1,)),),
            is_processing=True,
        ))
        for _ in range(5):
            await pilot.pause()
        assert list(pilot.app.query(Markdown)) == []

        # iter 2 starts streaming text.
        pilot.app.push(AppState(
            turns=(_running_turn(
                "T1", "c1", "hi", text="final answer", tools=(tc1,),
            ),),
            is_processing=True,
        ))
        for _ in range(5):
            await pilot.pause()
        mds = list(pilot.app.query(Markdown))
        assert len(mds) == 1, f"expected exactly one Markdown, got {len(mds)}"


async def test_segments_render_in_chronological_order():
    """Thinking text → tool → final answer must render in that order
    inside the turn block (so the answer is BELOW the tool call, not above)."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        segs = (
            TextSegment(text="Let me check this file..."),
            ToolCallView(
                tool_call_id="tc1", tool_name="read",
                args={"path": "a.py"}, status="done",
            ),
            TextSegment(text="Final answer: X."),
        )
        turn = TurnView(
            turn_id="T1", cmd_id="c1", user_text="review",
            segments=segs, status="done",
        )
        pilot.app.push(AppState(turns=(turn,)))
        for _ in range(5):
            await pilot.pause()

        block = pilot.app.query_one(TurnBlock)
        kinds = [
            "Markdown" if isinstance(c, Markdown) else type(c).__name__
            for c in block.children
            if isinstance(c, (Markdown, ToolCallEntry))
        ]
        assert kinds == ["Markdown", "ToolCallEntry", "Markdown"], (
            f"segments not in chronological order: {kinds}"
        )


async def test_intermediate_thinking_text_visible_between_tools():
    """When the model streams 'thinking' text before calling tools,
    that text must be displayed above the tool call (not wiped by the
    final answer)."""
    async with _Host().run_test() as pilot:
        await pilot.pause()
        segs = (
            TextSegment(text="I'll start by reading the config."),
            ToolCallView(
                tool_call_id="tc1", tool_name="read",
                args={"path": "config.py"}, status="done",
            ),
            TextSegment(text="Now I need to check the entrypoint."),
            ToolCallView(
                tool_call_id="tc2", tool_name="read",
                args={"path": "main.py"}, status="done",
            ),
            TextSegment(text="The architecture is X."),
        )
        turn = TurnView(
            turn_id="T1", cmd_id="c1", user_text="review",
            segments=segs, status="done",
        )
        pilot.app.push(AppState(turns=(turn,)))
        for _ in range(5):
            await pilot.pause()

        mds = [str(m._markdown or "") for m in pilot.app.query(Markdown)]
        assert any("start by reading" in t for t in mds), \
            "first thinking text missing"
        assert any("check the entrypoint" in t for t in mds), \
            "second thinking text missing"
        assert any("architecture is X" in t for t in mds), \
            "final answer missing"


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


async def test_state_change_does_not_auto_scroll_to_end():
    """Auto-scroll on every state change is removed. The scroll position
    must not be force-pushed to the bottom by _on_state_change."""
    from textual.containers import VerticalScroll

    async with _Host().run_test() as pilot:
        await pilot.pause()
        # Build enough turns to overflow the viewport.
        many_turns = tuple(
            _done_turn(f"T{i}", f"q{i}", with_tool=True) for i in range(20)
        )
        pilot.app.push(AppState(turns=many_turns))
        for _ in range(5):
            await pilot.pause()
        scroll = pilot.app.query_one("#chat-scroll", VerticalScroll)
        # Manually scroll to top.
        scroll.scroll_home(animate=False)
        await pilot.pause()
        top_y = scroll.scroll_y

        # Push another turn — old behavior would force scroll_end.
        new_turns = many_turns + (
            _done_turn("T_new", "fresh", with_tool=True),
        )
        pilot.app.push(AppState(turns=new_turns))
        for _ in range(5):
            await pilot.pause()

        # The scroll position should not have jumped to the end.
        assert scroll.scroll_y <= top_y + 1, (
            f"scroll auto-jumped from {top_y} to {scroll.scroll_y} — auto-scroll "
            "should be removed"
        )
