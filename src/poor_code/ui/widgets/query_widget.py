"""QueryWidget — inline interactive option picker for option-bearing queries
(choose/approve/confirm). Arrow keys move, Enter selects → app.answer_query.
Free-text 'clarify' queries don't use this; they go through the prompt box."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from poor_code.ui.store import QuerySegment


class QueryWidget(Static):
    DEFAULT_CSS = "QueryWidget { height: auto; }"

    def __init__(self, seg: QuerySegment) -> None:
        super().__init__(classes="query-widget")
        self._seg = seg

    def compose(self) -> ComposeResult:
        yield Static(f"❓ {self._seg.prompt}", classes="query-prompt")
        ol = OptionList(*[Option(o) for o in self._seg.options], id="query-options")
        yield ol

    def on_mount(self) -> None:
        ol = self.query_one("#query-options", OptionList)
        if self._seg.options:
            ol.highlighted = 0
        ol.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if 0 <= idx < len(self._seg.options):
            chosen = self._seg.options[idx]
            self.app.answer_query(chosen, chosen_option=chosen)
        event.stop()
