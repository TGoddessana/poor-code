import json

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from poor_code.ui.store import AppState, ToolCallView


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
    ToolCallEntry:not(.collapsed) > .tool-detail {
        display: block;
    }
    """

    def __init__(self, tc: ToolCallView) -> None:
        super().__init__(classes="tool-entry collapsed")
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
        self.toggle_class("collapsed")

    def on_key(self, event) -> None:
        if event.key == "enter" or event.key == "space":
            self.toggle_class("collapsed")
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


class ChatLog(Widget):
    """Renders state.turns. Naive remount on each state change.

    Diff-aware updates are deferred; performance is fine for hundreds of turns.
    """

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat-scroll")

    def on_mount(self) -> None:
        self.watch(self.app, "app_state", self._on_state_change)

    def _on_state_change(self, state: AppState) -> None:
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.remove_children()
        for turn in state.turns:
            scroll.mount(Static(f"> {turn.user_text}", classes="user-msg"))
            if turn.assistant_text:
                scroll.mount(Static(turn.assistant_text, classes="assistant-msg"))
            for tc in turn.tool_calls:
                marker = {"running": "…", "done": "✓", "failed": "✗"}[tc.status]
                scroll.mount(Static(
                    f"  {marker} {tc.tool_name}", classes=f"tool-{tc.status}"
                ))
            if turn.status == "failed" and turn.error:
                scroll.mount(Static(f"  error: {turn.error}", classes="turn-error"))
