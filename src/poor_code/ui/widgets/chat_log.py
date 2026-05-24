import json
from typing import Literal

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from poor_code.ui.store import AppState, ToolCallView
from poor_code.ui.widgets.banner import Banner


class ThinkingMascot(Widget):
    """마지막 TurnBlock 안에 마운트되어 에이전트 상태를 표정으로 표현."""

    DEFAULT_CSS = """
    ThinkingMascot {
        height: auto;
        margin-bottom: 1;
    }
    """

    PENDING_FRAMES = [" ( ˘_˘)", "(¬_¬) ", "(-_-) ", "(-_-) zZ", "(O_O)!", "(°o°) "]
    RUNNING_FRAMES = ["(ó_ò) ", "(ง •_•)ง", "(°▽°) "]

    def __init__(self, mode: Literal["pending", "running"]) -> None:
        super().__init__(classes="thinking-mascot")
        self._mode = mode
        self._frames = self.PENDING_FRAMES if mode == "pending" else self.RUNNING_FRAMES
        self._index = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Static(self._frames[0], classes="mascot-frame")

    def on_mount(self) -> None:
        interval = 0.7 if self._mode == "pending" else 0.4
        self._timer = self.set_interval(interval, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._index = (self._index + 1) % len(self._frames)
        self.query_one(".mascot-frame", Static).update(self._frames[self._index])


class ToolCallEntry(Widget):
    """Collapsible tool call display. Click or Enter/Space to toggle."""

    DEFAULT_CSS = """
    ToolCallEntry {
        height: auto;
        margin-bottom: 1;
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

    def compose(self) -> ComposeResult:
        marker = {"running": "…", "done": "✓", "failed": "✗"}[self._tc.status]
        preview = self._format_preview(self._tc.args)
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

    def on_click(self) -> None:
        self.toggle_class("expanded")

    def on_key(self, event) -> None:
        if event.key == "enter" or event.key == "space":
            self.toggle_class("expanded")
            event.prevent_default()
            event.stop()

    def refresh_from(self, tc: ToolCallView) -> None:
        """Update display when the underlying ToolCallView changes."""
        if tc == self._tc:
            return
        self._tc = tc
        self.remove_children()
        for child in self.compose():
            self.mount(child)

    @staticmethod
    def _format_preview(args: dict) -> str:
        parts = [f"{k}={v!r}" for k, v in args.items()]
        preview = ", ".join(parts)
        if len(preview) > 80:
            preview = preview[:77] + "..."
        return preview

    @staticmethod
    def _format_value(value: object) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)


class TurnBlock(Widget):
    """A single turn in the chat log. Composes children via compose()."""

    def __init__(self, turn) -> None:
        super().__init__(classes="turn-block")
        self._turn = turn

    def compose(self) -> ComposeResult:
        turn = self._turn
        yield Static(f"> {turn.user_text}", classes="user-msg")
        if turn.assistant_text:
            yield Markdown(turn.assistant_text, classes="assistant-msg")
        for tc in turn.tool_calls:
            yield ToolCallEntry(tc)
        if turn.status == "failed" and turn.error:
            yield Static(f"  error: {turn.error}", classes="turn-error")

    def refresh_from(self, turn) -> None:
        """Update children in-place (only for the last turn during streaming)."""
        self._turn = turn

        # --- assistant text ---
        md_list = list(self.query(".assistant-msg"))
        if turn.assistant_text:
            if md_list:
                md_list[0].update(turn.assistant_text)
            else:
                self.mount(Markdown(turn.assistant_text, classes="assistant-msg"))
        elif md_list:
            md_list[0].remove()

        # --- tool calls ---
        existing_tools = list(self.query(ToolCallEntry))
        for i, tc in enumerate(turn.tool_calls):
            if i < len(existing_tools):
                existing_tools[i].refresh_from(tc)
            else:
                self.mount(ToolCallEntry(tc))
        for w in existing_tools[len(turn.tool_calls):]:
            w.remove()

        # --- ThinkingMascot: tool calls 뒤에 마운트 (항상 맨 아래) ---
        mascots = list(self.query(ThinkingMascot))
        desired_mode: Literal["pending", "running"] | None = None
        if turn.status in ("pending", "running") and not turn.assistant_text:
            if turn.status == "running" and turn.tool_calls:
                desired_mode = "running"
            else:
                desired_mode = "pending"

        if desired_mode is None:
            for m in mascots:
                m.remove()
        elif not mascots:
            self.mount(ThinkingMascot(desired_mode))
        elif mascots[0]._mode != desired_mode:
            mascots[0].remove()
            self.mount(ThinkingMascot(desired_mode))
        # else: same mode already mounted — leave it

        # --- error ---
        err_list = list(self.query(".turn-error"))
        if turn.status == "failed" and turn.error:
            if err_list:
                err_list[0].update(f"  error: {turn.error}")
            else:
                self.mount(Static(f"  error: {turn.error}", classes="turn-error"))
        else:
            for w in err_list:
                w.remove()


class ChatLog(Widget):
    """Renders state.turns. Diff-aware: only mounts new turns; updates last turn in-place."""

    DEFAULT_CSS = "ChatLog { height: 1fr; }"

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Banner(), id="chat-scroll")

    def on_mount(self) -> None:
        self.watch(self.app, "app_state", self._on_state_change)

    def _on_state_change(self, state: AppState) -> None:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        self._sync_turns(scroll, state.turns)
        scroll.scroll_end(animate=False)

    def _sync_turns(self, scroll: VerticalScroll, turns: tuple) -> None:
        existing = list(scroll.query(TurnBlock))

        if len(turns) < len(existing):
            scroll.remove_children()
            existing = []

        for turn in turns[len(existing):]:
            scroll.mount(TurnBlock(turn))

        if turns and existing:
            last_turn = turns[-1]
            last_block = existing[-1]
            if (last_block._turn.status != last_turn.status
                    or last_turn.status in ("running", "pending")):
                last_block.refresh_from(last_turn)
