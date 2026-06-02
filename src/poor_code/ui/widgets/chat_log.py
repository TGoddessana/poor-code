import json
import time

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from poor_code.ui.store import (
    AppState, NodeLabelSegment, TextSegment, ToolCallView,
)
from poor_code.ui.widgets.banner import Banner
from poor_code.ui.widgets.streaming_markdown import StreamingMarkdown

__all__ = ["ChatLog", "TurnBlock", "ToolCallEntry", "StaticSegment", "SPINNER_FRAMES"]


def _render_segment(seg) -> str:
    if isinstance(seg, NodeLabelSegment):
        return f"▸ {seg.node}"
    return str(seg)


class StaticSegment(Widget):
    """Immutable, append-once segment (node label / query / plan). Re-renders only on change."""

    DEFAULT_CSS = "StaticSegment { height: auto; }"

    def __init__(self, seg) -> None:
        super().__init__(classes="static-segment")
        self._seg = seg

    def compose(self) -> ComposeResult:
        yield Static(_render_segment(self._seg), classes="static-segment-body")

    def refresh_from(self, seg) -> None:
        if seg == self._seg:
            return
        self._seg = seg
        self.remove_children()
        for child in self.compose():
            self.mount(child)

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class ToolCallEntry(Widget):
    """Collapsible tool call display. Click or Enter/Space to toggle."""

    DEFAULT_CSS = """
    ToolCallEntry {
        height: auto;
    }
    ToolCallEntry > .tool-detail {
        display: none;
    }
    ToolCallEntry.expanded > .tool-detail {
        display: block;
    }
    """

    def __init__(self, tc: ToolCallView) -> None:
        super().__init__(classes="tool-entry")
        self._tc = tc
        self._timer = None
        self._spin_index = 0

    def compose(self) -> ComposeResult:
        marker = self._marker()
        preview = self._format_preview(self._tc.tool_name, self._tc.args)
        yield Static(
            f"  {marker} {self._tc.tool_name} {preview}",
            classes=f"tool-summary tool-{self._tc.status}",
        )
        detail_parts = [f"    args: {json.dumps(self._tc.args, ensure_ascii=False)}"]
        if self._tc.status == "done" and self._tc.result is not None:
            detail_parts.append(f"    result: {self._format_value(self._tc.result)}")
        if self._tc.status == "failed" and self._tc.error:
            detail_parts.append(f"    error: {self._tc.error}")
        yield Static("\n".join(detail_parts), classes="tool-detail")

    def on_mount(self) -> None:
        if self._tc.status == "running":
            self._start_spinner()

    def on_unmount(self) -> None:
        self._stop_spinner()

    def on_click(self) -> None:
        self.toggle_class("expanded")

    def on_key(self, event) -> None:
        if event.key == "enter" or event.key == "space":
            self.toggle_class("expanded")
            event.prevent_default()
            event.stop()

    def refresh_from(self, tc: ToolCallView) -> None:
        if tc == self._tc:
            return
        was_running = self._tc.status == "running"
        self._tc = tc
        if was_running and tc.status != "running":
            self._stop_spinner()
        self.remove_children()
        for child in self.compose():
            self.mount(child)
        if tc.status == "running" and self._timer is None:
            self._start_spinner()

    def _marker(self) -> str:
        if self._tc.status == "running":
            return SPINNER_FRAMES[self._spin_index]
        return {"done": "✓", "failed": "✗"}.get(self._tc.status, "…")

    def _start_spinner(self) -> None:
        if self._timer is None:
            self._timer = self.set_interval(0.1, self._tick)

    def _stop_spinner(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._spin_index = (self._spin_index + 1) % len(SPINNER_FRAMES)
        summaries = list(self.query(".tool-summary"))
        if summaries:
            preview = self._format_preview(self._tc.tool_name, self._tc.args)
            summaries[0].update(f"  {SPINNER_FRAMES[self._spin_index]} {self._tc.tool_name} {preview}")

    @staticmethod
    def _format_preview(tool_name: str, args: dict) -> str:
        match tool_name:
            case "read":
                return args.get("path", "")
            case "bash":
                cmd = args.get("command", "")
                return (cmd[:60] + "...") if len(cmd) > 60 else cmd
            case "write" | "edit":
                return args.get("path", "")
            case _:
                parts = [f"{k}={v!r}" for k, v in args.items()]
                preview = ", ".join(parts)
                return preview[:77] + "..." if len(preview) > 80 else preview

    @staticmethod
    def _format_value(value: object) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)


def _format_turn_footer(turn, fallback_model: str) -> str:
    """One-line dim footer under an assistant turn. Shows `<model> · <duration>s`.
    During `running`, duration is live-elapsed from `turn.started_at`.
    During `done`/`failed`, duration is the authoritative `turn.duration_sec`.
    `fallback_model` is used while the turn is running (turn.model not yet set
    by TurnEnded)."""
    if turn.status == "pending":
        return ""
    model = turn.model or fallback_model or ""
    if turn.status == "running":
        if turn.started_at is None:
            return ""
        elapsed = time.monotonic() - turn.started_at
        return f"  {model} · {elapsed:.1f}s"
    if turn.duration_sec is None:
        return ""
    return f"  {model} · {turn.duration_sec:.1f}s"


class TurnBlock(Widget):
    """A single turn in the chat log. Composes children via compose()."""

    DEFAULT_CSS = """
    TurnBlock {
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(self, turn) -> None:
        super().__init__(classes="turn-block")
        self._turn = turn
        self._tick_timer = None

    def compose(self) -> ComposeResult:
        turn = self._turn
        yield Static(turn.user_text, classes="user-msg")
        for seg in turn.segments:
            yield self._make_segment_widget(seg)
        if turn.status == "failed" and turn.error:
            yield Static(f"  error: {turn.error}", classes="turn-error")
        footer_text = _format_turn_footer(turn, fallback_model=self._current_model())
        footer = Static(footer_text, classes="turn-footer", id="turn-footer")
        footer.display = bool(footer_text)
        yield footer

    def on_mount(self) -> None:
        if self._turn.status == "running":
            self._start_tick()

    def on_unmount(self) -> None:
        self._stop_tick()

    def _start_tick(self) -> None:
        if self._tick_timer is None:
            self._tick_timer = self.set_interval(0.1, self._tick_footer)
            self._tick_footer()

    def _stop_tick(self) -> None:
        if self._tick_timer is not None:
            self._tick_timer.stop()
            self._tick_timer = None

    def _tick_footer(self) -> None:
        footers = list(self.query("#turn-footer"))
        if footers:
            text = _format_turn_footer(
                self._turn, fallback_model=self._current_model()
            )
            footers[0].update(text)
            footers[0].display = bool(text)

    def _current_model(self) -> str:
        state = getattr(self.app, "app_state", None)
        if state is None:
            return ""
        return state.model or ""

    def _make_segment_widget(self, seg) -> Widget:
        if isinstance(seg, TextSegment):
            md = StreamingMarkdown(seg.text, classes="assistant-msg")
            self._apply_assistant_status_class(md, self._turn.status)
            return md
        if isinstance(seg, ToolCallView):
            return ToolCallEntry(seg)
        return StaticSegment(seg)

    @staticmethod
    def _apply_assistant_status_class(md, status: str) -> None:
        md.set_class(status == "pending", "status-pending")
        md.set_class(status == "failed", "status-failed")

    def refresh_from(self, turn) -> None:
        """Update children in-place (only for the last turn during streaming).

        Segments render in chronological order between user-msg and the
        error trailer; new segments mount just before that trailer."""
        self._turn = turn

        # Existing segment widgets in DOM order.
        existing_segs: list[Widget] = [
            c for c in self.children
            if isinstance(c, (Markdown, ToolCallEntry, StaticSegment))
        ]
        # Anchor for new segment mounts — segments must stay above both the
        # error trailer and the per-turn footer. The footer is mounted during
        # compose() (even when hidden for pending turns), so without anchoring
        # against it, streamed segments land after it in the DOM.
        err_list = list(self.query(".turn-error"))
        footer_list = list(self.query("#turn-footer"))
        anchor = (
            err_list[0] if err_list
            else (footer_list[0] if footer_list else None)
        )

        for i, seg in enumerate(turn.segments):
            if i < len(existing_segs):
                w = existing_segs[i]
                if isinstance(seg, TextSegment) and isinstance(w, StreamingMarkdown):
                    self.app.call_later(w.write_delta, seg.text)
                elif isinstance(seg, ToolCallView) and isinstance(w, ToolCallEntry):
                    w.refresh_from(seg)
                elif isinstance(seg, NodeLabelSegment) and isinstance(w, StaticSegment):
                    w.refresh_from(seg)
                else:
                    # Kind mismatch — replace.
                    w.remove()
                    new_w = self._make_segment_widget(seg)
                    if i + 1 < len(existing_segs):
                        self.mount(new_w, before=existing_segs[i + 1])
                    elif anchor is not None:
                        self.mount(new_w, before=anchor)
                    else:
                        self.mount(new_w)
            else:
                new_w = self._make_segment_widget(seg)
                if anchor is not None:
                    self.mount(new_w, before=anchor)
                else:
                    self.mount(new_w)
        for w in existing_segs[len(turn.segments):]:
            w.remove()

        # Sync assistant-msg status classes to the new turn status.
        for md in self.query(StreamingMarkdown):
            self._apply_assistant_status_class(md, turn.status)

        # --- error ---
        err_list = list(self.query(".turn-error"))
        if turn.status == "failed" and turn.error:
            if err_list:
                err_list[0].update(f"  error: {turn.error}")
            else:
                # Mount before the footer so footer stays at the bottom.
                footer_anchor = list(self.query("#turn-footer"))
                err_widget = Static(f"  error: {turn.error}", classes="turn-error")
                if footer_anchor:
                    self.mount(err_widget, before=footer_anchor[0])
                else:
                    self.mount(err_widget)
        else:
            for w in err_list:
                w.remove()

        # --- per-turn footer (live ticking handled by interval; this updates
        # immediately on every state push so done→duration is reflected at once).
        footers = list(self.query("#turn-footer"))
        if footers:
            text = _format_turn_footer(turn, fallback_model=self._current_model())
            footers[0].update(text)
            footers[0].display = bool(text)

        # Start/stop the live tick based on status transition.
        if turn.status == "running" and self._tick_timer is None:
            self._start_tick()
        elif turn.status != "running" and self._tick_timer is not None:
            self._stop_tick()
            footers = list(self.query("#turn-footer"))
            if footers:
                text = _format_turn_footer(
                    turn, fallback_model=self._current_model()
                )
                footers[0].update(text)
                footers[0].display = bool(text)


class ChatLog(Widget):
    """Renders state.turns. Diff-aware: only mounts new turns; updates last turn in-place."""

    DEFAULT_CSS = "ChatLog { height: 1fr; }"

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Banner(), id="chat-scroll")

    def on_mount(self) -> None:
        self.watch(self.app, "app_state", self._on_state_change)
        self.query_one("#chat-scroll", VerticalScroll).anchor()

    def _on_state_change(self, state: AppState) -> None:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        self._sync_turns(scroll, state.turns)

    def _sync_turns(self, scroll: VerticalScroll, turns: tuple) -> None:
        existing = list(scroll.query(TurnBlock))

        if len(turns) < len(existing):
            scroll.remove_children()
            existing = []

        if len(turns) > len(existing):
            # New turn(s) — compose() renders them with their initial state.
            # Do NOT refresh existing[-1]: it belongs to a *prior* turn whose
            # content must stay intact.
            for turn in turns[len(existing):]:
                scroll.mount(TurnBlock(turn))
            return

        # Same length: update the active (last) turn in-place.
        if turns and existing:
            last_turn = turns[-1]
            last_block = existing[-1]
            if (last_block._turn.status != last_turn.status
                    or last_turn.status in ("running", "pending")):
                last_block.refresh_from(last_turn)
