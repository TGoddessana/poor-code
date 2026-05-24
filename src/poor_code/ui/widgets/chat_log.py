import json

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from poor_code.ui.store import AppState, ToolCallView
from poor_code.ui.widgets.banner import Banner


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

        md_list = list(self.query(".assistant-msg"))
        if turn.assistant_text:
            if md_list:
                md_list[0].update(turn.assistant_text)
            else:
                self.mount(Markdown(turn.assistant_text, classes="assistant-msg"))
        elif md_list:
            md_list[0].remove()

        existing_tools = list(self.query(ToolCallEntry))
        for i, tc in enumerate(turn.tool_calls):
            if i < len(existing_tools):
                existing_tools[i].refresh_from(tc)
            else:
                self.mount(ToolCallEntry(tc))
        for w in existing_tools[len(turn.tool_calls):]:
            w.remove()

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

        if turns and existing and turns[-1].status in ("running", "pending"):
            existing[-1].refresh_from(turns[-1])
