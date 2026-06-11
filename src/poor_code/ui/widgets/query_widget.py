"""QueryWidget — inline interactive option picker for option-bearing queries
(choose/approve/confirm). Arrow keys move, Enter selects → app.answer_query.
Free-text 'clarify' queries don't use this; they go through the prompt box."""
from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from poor_code.ui.store import QuerySegment


class _PickList(OptionList):
    """OptionList where a mouse click only HIGHLIGHTS (and focuses) — it does not
    commit. Commit is always an explicit Enter. Textual's default OptionList
    commits on a single click, which surprised users mid-interview; this keeps the
    keyboard the source of truth and makes click a 'move the cursor here' gesture."""

    def _on_click(self, event: events.Click) -> None:
        # prevent_default() is essential: Textual dispatches `_on_click` from every
        # class in the MRO, so without it the base OptionList._on_click still runs
        # and commits the selection. prevent_default breaks that MRO walk before the
        # base handler, leaving Enter as the only commit path.
        event.prevent_default()
        event.stop()
        clicked = event.style.meta.get("option")
        if clicked is not None and not self._options[clicked].disabled:
            self.highlighted = clicked
            self.focus()

    def _on_key(self, event: events.Key) -> None:
        """The picker owns the keyboard while a question is awaiting. Esc is
        handed to the app's interrupt action; arrows/Enter are left for the
        base OptionList (option navigation/select). All other keys are
        swallowed — typing must NOT reach the prompt box, otherwise the user's
        answer could leak into the next turn on Enter. The only way to leave
        the picker is Enter (commit an option) or Esc (interrupt)."""
        if event.key == "escape" and hasattr(self.app, "action_interrupt"):
            self.app.action_interrupt()
            event.prevent_default()
            event.stop()
            return
        if event.key in {"enter", "up", "down", "left", "right", "tab"}:
            return
        if event.character or (len(event.key) == 1 and event.key):
            event.prevent_default()
            event.stop()


class QueryWidget(Static):
    DEFAULT_CSS = "QueryWidget { height: auto; }"

    def __init__(self, seg: QuerySegment) -> None:
        super().__init__(classes="query-widget")
        self._seg = seg

    def compose(self) -> ComposeResult:
        yield Static(
            f"[b $warning]❓  Question[/]  [b]{self._seg.prompt}[/]",
            classes="query-prompt",
            markup=True,
        )
        ol = _PickList(*[Option(o) for o in self._seg.options], id="query-options")
        yield ol
        yield Static(
            "[dim]↑↓ move · Enter to select · Esc to challenge[/dim]",
            classes="query-hint",
            markup=True,
        )

    def on_mount(self) -> None:
        ol = self.query_one("#query-options", OptionList)
        if self._seg.options:
            ol.highlighted = 0
        # Focus the picker so the user's keyboard is owned by the question, not
        # the prompt box. We deliberately do NOT also focus #prompt-input: the
        # user asked that the picker keep focus while a query is awaiting, and
        # the prompt box must not visually blink or steal the next keypress.
        # Defer until after layout — when mounted dynamically into the scrolling
        # chat log, focusing inside on_mount can land before layout and silently
        # fail to take. In unit harnesses without a prompt box, the picker is
        # still focusable so the test path keeps working.
        self.call_after_refresh(ol.focus)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if 0 <= idx < len(self._seg.options):
            chosen = self._seg.options[idx]
            self.app.answer_query(chosen, chosen_option=chosen)
        event.stop()

    def on_unmount(self) -> None:
        """When the picker is dismissed (option picked or Esc interrupted),
        hand the keyboard back to the prompt box so the next keypress — the
        follow-up answer, the steering text, the next question — goes to the
        prompt box. We focus immediately rather than after a refresh tick:
        chat_log's diff removes the picker on the same loop turn the answer
        arrives, and the prompt box is a static sibling that is always in
        the tree, so deferring risks focus falling through to chat-scroll."""
        app = getattr(self, "app", None)
        if app is None:
            return
        try:
            prompt = app.screen.query_one("#prompt-input", Input)
        except Exception:
            return
        prompt.focus()
