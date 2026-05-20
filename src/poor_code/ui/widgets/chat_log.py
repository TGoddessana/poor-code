from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from poor_code.ui.store import AppState


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
