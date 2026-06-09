import json
import time
from dataclasses import dataclass, field

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from poor_code.ui.store import (
    AppState, NodeContextSegment, NodeLabelSegment, NodeRawOutputSegment,
    NodeResultSegment, NodeThinkingSegment, PlanSegment, QuerySegment,
    ReportSegment, TextSegment, ToolCallView, UserAnswerSegment,
)


@dataclass
class NodeGroup:
    """A render group: an optional node label header + the segments that belong to it.
    label is None for segments emitted before the first NodeLabelSegment (fast_path)."""
    label: object | None
    body: list = field(default_factory=list)


def group_segments(segments) -> list:
    """Fold a flat segment list into per-node groups. Each NodeLabelSegment opens a
    new group; subsequent non-label segments belong to it. Leading non-label
    segments form an initial label=None group."""
    groups: list[NodeGroup] = []
    current: NodeGroup | None = None
    for seg in segments:
        if isinstance(seg, NodeLabelSegment):
            current = NodeGroup(label=seg, body=[])
            groups.append(current)
        else:
            if current is None:
                current = NodeGroup(label=None, body=[])
                groups.append(current)
            current.body.append(seg)
    return groups
from poor_code.ui.widgets.banner import Banner
from poor_code.ui.widgets.query_widget import QueryWidget
from poor_code.ui.widgets.streaming_markdown import StreamingMarkdown

__all__ = ["ChatLog", "TurnBlock", "ToolCallEntry", "StaticSegment", "SPINNER_FRAMES"]


def _node_label_text(seg, *, marker: str = "▸", suffix_extra: str = "") -> str:
    gate = "  ⚠ decision needed" if seg.node.endswith("_gate") and "confirm" in seg.node else ""
    text = seg.activity or seg.node
    retry = f" (×{seg.retry + 1})" if seg.retry else ""
    m = marker
    if marker == "▸" and getattr(seg, "status", "running") == "interrupted":
        m = "⏸"
    return f"{m} {text}{retry}{suffix_extra}{gate}"


def _render_segment(seg) -> str:
    if isinstance(seg, NodeLabelSegment):
        return _node_label_text(seg)
    if isinstance(seg, NodeResultSegment):
        head = f"  ⤷ {seg.headline}"
        if seg.detail:
            head += "\n" + "\n".join(f"     {d}" for d in seg.detail)
        return head
    if isinstance(seg, UserAnswerSegment):
        return f"↳ {seg.text}"
    if isinstance(seg, QuerySegment):
        lines = [f"❓ {seg.prompt}"]
        for i, opt in enumerate(seg.options, start=1):
            lines.append(f"   [{i}] {opt}")
        return "\n".join(lines)
    if isinstance(seg, PlanSegment):
        return "📋 Plan\n" + "\n".join(f"   {ln}" for ln in seg.lines)
    if isinstance(seg, ReportSegment):
        icon = "✅" if seg.outcome == "succeeded" else "⚠️"
        body = [f"{icon} {seg.summary}"]
        body += [f"   {ln}" for ln in seg.lines]
        return "\n".join(body)
    return str(seg)


class StaticSegment(Widget):
    """Immutable, append-once segment (node label / query / plan). Re-renders only on change."""

    DEFAULT_CSS = "StaticSegment { height: auto; }"

    def __init__(self, seg) -> None:
        super().__init__(classes="static-segment")
        self._seg = seg

    def compose(self) -> ComposeResult:
        cls = "static-segment-body"
        if isinstance(self._seg, UserAnswerSegment):
            cls += " user-answer"
        elif isinstance(self._seg, NodeResultSegment):
            cls += " node-result"
        elif isinstance(self._seg, NodeLabelSegment):
            cls += " node-label"
        yield Static(_render_segment(self._seg), classes=cls)

    def refresh_from(self, seg) -> None:
        if seg == self._seg:
            return
        self._seg = seg
        self.remove_children()
        for child in self.compose():
            self.mount(child)

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class NodeLabelView(Widget):
    """A graph-node header (`▸ Exploring the codebase`). When it is the ACTIVE node
    — the trailing segment of a still-running turn — it animates a spinner and an
    elapsed counter so a long, prose-less structured LLM call (e.g. the interviewer
    thinking) doesn't look frozen. The timer runs independently of state pushes,
    which is essential: no events arrive during the in-flight call itself."""

    DEFAULT_CSS = "NodeLabelView { height: auto; }"

    def __init__(self, seg) -> None:
        super().__init__(classes="static-segment")
        self._seg = seg
        self._active = False
        self._timer = None
        self._spin = 0
        self._t0: float | None = None

    def compose(self) -> ComposeResult:
        yield Static(self._text(), classes="static-segment-body node-label")

    def _text(self) -> str:
        if self._active:
            spinner = SPINNER_FRAMES[self._spin]
            elapsed = f"  {time.monotonic() - self._t0:.0f}s" if self._t0 is not None else ""
            return _node_label_text(self._seg, marker=spinner, suffix_extra=elapsed)
        return _node_label_text(self._seg)

    def refresh_from(self, seg) -> None:
        if seg != self._seg:
            self._seg = seg
            self._render_now()

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._t0 = time.monotonic()
            self._spin = 0
            if self._timer is None:
                self._timer = self.set_interval(0.1, self._tick)
        elif self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._render_now()

    def _tick(self) -> None:
        self._spin = (self._spin + 1) % len(SPINNER_FRAMES)
        self._render_now()

    def _render_now(self) -> None:
        bodies = list(self.query(".static-segment-body"))
        if bodies:
            bodies[0].update(self._text())

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None


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
        if was_running and tc.status in ("done", "failed"):
            self.add_class("tool-done-flash")
            self.set_timer(0.6, lambda: self.remove_class("tool-done-flash"))
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


class NodeCard(Widget):
    """A collapsible card for one graph node: header (label + timer/status) + body
    (context, thinking stream, tool calls, raw output). The current node auto-expands.
    Body widgets are pre-built by the owning TurnBlock so query interactivity and
    assistant-status classes are applied consistently; the TurnBlock also diffs the
    body in place on refresh (so streaming text / a focused query picker survive)."""

    DEFAULT_CSS = """
    NodeCard { height: auto; }
    NodeCard > .node-card-body { display: none; height: auto; padding-left: 2; }
    NodeCard.expanded > .node-card-body { display: block; }
    """

    def __init__(self, label, body_widgets: list, expand: bool, label_active: bool) -> None:
        super().__init__(classes="node-card")
        self.node = label.node
        self._label = label
        self._body_widgets = body_widgets
        self._expand = expand
        self._label_active = label_active

    def compose(self) -> ComposeResult:
        yield NodeLabelView(self._label)
        with Container(classes="node-card-body"):
            for w in self._body_widgets:
                yield w

    def on_mount(self) -> None:
        self.set_class(self._expand, "expanded")
        self.header.set_active(self._label_active)

    @property
    def header(self) -> "NodeLabelView":
        return self.query_one(NodeLabelView)

    @property
    def body_container(self) -> Container:
        return self.query_one(".node-card-body", Container)

    def set_state(self, label, expand: bool, label_active: bool) -> None:
        self._label = label
        self._expand = expand
        self._label_active = label_active
        self.header.refresh_from(label)
        self.header.set_active(label_active)
        if expand:
            self.add_class("expanded")  # force-expand the current node; leave others as the user left them

    def on_click(self) -> None:
        self.toggle_class("expanded")

    # NOTE: no on_key toggle. NodeCard is not focusable, so an on_key handler would
    # only ever fire by bubbling up from a focused descendant (e.g. the query
    # picker's OptionList) — and stopping the event there kills that widget's own
    # Enter binding (the option-commit). Toggling is click-only; the current node
    # auto-expands so the keyboard path never needs it.


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
        yield Static(turn.user_text, classes="user-msg", markup=False)
        groups = group_segments(turn.segments)
        for i, g in enumerate(groups):
            if g.label is None:
                for seg in g.body:
                    yield self._make_segment_widget(seg)
            else:
                expand, label_active = self._card_flags(turn, groups, i)
                yield self._node_card_for(g, expand, label_active)
        if turn.status == "failed" and turn.error:
            yield Static(f"  error: {turn.error}", classes="turn-error", markup=False)
        conclusion = self._conclusion_text(turn)
        if conclusion:
            yield Static(conclusion, classes="turn-conclusion", markup=False)
        footer_text = _format_turn_footer(turn, fallback_model=self._current_model())
        footer = Static(footer_text, classes="turn-footer", id="turn-footer")
        footer.display = bool(footer_text)
        yield footer

    def _active_group_index(self, turn, groups) -> int:
        """The trailing node group is the 'current' node (auto-expanded) while running."""
        if turn.status != "running":
            return -1
        for i in range(len(groups) - 1, -1, -1):
            if groups[i].label is not None:
                return i
        return -1

    def _card_flags(self, turn, groups, i) -> tuple[bool, bool]:
        """(expand, label_active) for the card at group index i.
        expand: the current node auto-expands to show its thinking.
        label_active: the spinner animates ONLY while the label is the literal
        trailing segment (nothing produced/queried after it yet)."""
        expand = i == self._active_group_index(turn, groups)
        label_active = (
            turn.status == "running"
            and i == len(groups) - 1
            and not groups[i].body
        )
        return expand, label_active

    def _conclusion_text(self, turn) -> str:
        state = getattr(self.app, "app_state", None)
        conc = getattr(state, "turn_conclusion", None) if state else None
        turns = getattr(state, "turns", None) if state else None
        last_turn = turns[-1] if turns else None
        if not conc or turn is not last_turn:
            return ""
        reason, detail = conc
        return f"⏹ {reason}: {detail}" if detail else f"⏹ {reason}"

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

    def _query_interactive(self, seg) -> bool:
        from poor_code.ui.store import QuerySegment
        state = getattr(self.app, "app_state", None)
        return bool(
            isinstance(seg, QuerySegment) and seg.options
            and state is not None and state.awaiting_input
        )

    def _make_segment_widget(self, seg) -> Widget:
        if isinstance(seg, TextSegment):
            md = StreamingMarkdown(seg.text, classes="assistant-msg")
            self._apply_assistant_status_class(md, self._turn.status)
            return md
        if isinstance(seg, ToolCallView):
            return ToolCallEntry(seg)
        if self._query_interactive(seg):
            return QueryWidget(seg)
        if isinstance(seg, NodeContextSegment):
            return Static(Text(f"⤷ context  ({seg.summary})\n{seg.full}"), classes="node-context")
        if isinstance(seg, NodeThinkingSegment):
            return Static(Text(f"⤷ thinking\n{seg.text}"), classes="node-thinking")
        if isinstance(seg, NodeRawOutputSegment):
            return Static(Text(f"⤷ output\n{seg.raw}"), classes="node-rawoutput")
        if isinstance(seg, NodeLabelSegment):
            return NodeLabelView(seg)
        return StaticSegment(seg)

    def _node_card_for(self, group, expand: bool, label_active: bool) -> "NodeCard":
        body = [self._make_segment_widget(seg) for seg in group.body]
        return NodeCard(group.label, body, expand, label_active)

    @staticmethod
    def _apply_assistant_status_class(md, status: str) -> None:
        md.set_class(status == "pending", "status-pending")
        md.set_class(status == "failed", "status-failed")

    def _try_reuse_seg(self, w, seg) -> bool:
        """Update an existing segment widget in place when its kind matches `seg`.
        Returns False on a kind mismatch (caller replaces). Mirrors the per-type
        reuse the flat renderer used before grouping, so streaming text and a
        focused query picker survive refreshes."""
        if isinstance(seg, TextSegment) and isinstance(w, StreamingMarkdown):
            self.app.call_later(w.write_delta, seg.text)
            self._apply_assistant_status_class(w, self._turn.status)
            return True
        if isinstance(seg, ToolCallView) and isinstance(w, ToolCallEntry):
            w.refresh_from(seg)
            return True
        if isinstance(seg, NodeContextSegment) and isinstance(w, Static) and "node-context" in w.classes:
            w.update(Text(f"⤷ context  ({seg.summary})\n{seg.full}"))
            return True
        if isinstance(seg, NodeThinkingSegment) and isinstance(w, Static) and "node-thinking" in w.classes:
            w.update(Text(f"⤷ thinking\n{seg.text}"))
            return True
        if isinstance(seg, NodeRawOutputSegment) and isinstance(w, Static) and "node-rawoutput" in w.classes:
            w.update(Text(f"⤷ output\n{seg.raw}"))
            return True
        if isinstance(seg, QuerySegment) and self._query_interactive(seg) and isinstance(w, QueryWidget):
            return True  # keep the live picker (focus/selection) while still awaiting
        if isinstance(seg, (PlanSegment, ReportSegment, UserAnswerSegment, NodeResultSegment)) and isinstance(w, StaticSegment):
            w.refresh_from(seg)
            return True
        if isinstance(seg, QuerySegment) and not self._query_interactive(seg) and isinstance(w, StaticSegment):
            w.refresh_from(seg)
            return True
        return False

    def _diff_segments(self, parent, segs, anchor) -> None:
        """In-place positional diff of a pure-segment list into `parent`'s children.
        New widgets mount before `anchor` (None → appended)."""
        existing = [c for c in parent.children if not (anchor is not None and c is anchor)]
        for idx, seg in enumerate(segs):
            w = existing[idx] if idx < len(existing) else None
            if w is not None and self._try_reuse_seg(w, seg):
                continue
            new_w = self._make_segment_widget(seg)
            if w is not None:
                nxt = existing[idx + 1] if idx + 1 < len(existing) else anchor
                parent.mount(new_w, before=nxt) if nxt is not None else parent.mount(new_w)
                w.remove()
                existing[idx] = new_w
            else:
                parent.mount(new_w, before=anchor) if anchor is not None else parent.mount(new_w)
        for w in existing[len(segs):]:
            w.remove()

    def _refresh_card(self, card, group, expand: bool, label_active: bool) -> None:
        card.set_state(group.label, expand, label_active)
        self._diff_segments(card.body_container, group.body, anchor=None)

    def refresh_from(self, turn) -> None:
        """Update this turn's body in place (only the last turn is refreshed during
        streaming). Items — node cards and fast_path segments — are matched
        positionally; the footer is updated in place (never re-mounted) so its fixed
        id never collides with a still-pending async removal."""
        self._turn = turn
        groups = group_segments(turn.segments)

        # Desired top-level items: ("seg", seg) for fast_path bodies, ("card", group,
        # expand, label_active) for labelled groups.
        desired: list[tuple] = []
        for i, g in enumerate(groups):
            if g.label is None:
                desired += [("seg", seg) for seg in g.body]
            else:
                expand, label_active = self._card_flags(turn, groups, i)
                desired.append(("card", g, expand, label_active))

        err_list = list(self.query(".turn-error"))
        conc_list = list(self.query(".turn-conclusion"))
        footer_list = list(self.query("#turn-footer"))
        trailers = {id(w) for w in (*err_list, *conc_list, *footer_list)}
        anchor = (err_list or conc_list or footer_list or [None])[0]
        existing = [c for c in self.children
                    if "user-msg" not in c.classes and id(c) not in trailers]

        for idx, item in enumerate(desired):
            w = existing[idx] if idx < len(existing) else None
            if w is not None and self._reuse_item(w, item):
                continue
            new_w = self._make_item_widget(item)
            if w is not None:
                nxt = existing[idx + 1] if idx + 1 < len(existing) else anchor
                self.mount(new_w, before=nxt) if nxt is not None else self.mount(new_w)
                w.remove()
                existing[idx] = new_w
            else:
                self.mount(new_w, before=anchor) if anchor is not None else self.mount(new_w)
        for w in existing[len(desired):]:
            w.remove()

        self._sync_trailer(".turn-error",
                           f"  error: {turn.error}" if turn.status == "failed" and turn.error else "")
        self._sync_trailer(".turn-conclusion", self._conclusion_text(turn))

        footers = list(self.query("#turn-footer"))
        if footers:
            text = _format_turn_footer(turn, fallback_model=self._current_model())
            footers[0].update(text)
            footers[0].display = bool(text)

        if turn.status == "running" and self._tick_timer is None:
            self._start_tick()
        elif turn.status != "running" and self._tick_timer is not None:
            self._stop_tick()

    def _reuse_item(self, w, item) -> bool:
        if item[0] == "seg":
            return self._try_reuse_seg(w, item[1])
        _, group, expand, label_active = item
        if isinstance(w, NodeCard) and w.node == group.label.node:
            self._refresh_card(w, group, expand, label_active)
            return True
        return False

    def _make_item_widget(self, item) -> Widget:
        if item[0] == "seg":
            return self._make_segment_widget(item[1])
        _, group, expand, label_active = item
        return self._node_card_for(group, expand, label_active)

    def _sync_trailer(self, selector: str, text: str) -> None:
        """Keep a single optional trailer (error / conclusion) in sync, mounted just
        above the footer. Updated in place; removed when empty."""
        existing = list(self.query(selector))
        if text:
            if existing:
                existing[0].update(text)
            else:
                cls = selector.lstrip(".")
                footer = list(self.query("#turn-footer"))
                w = Static(text, classes=cls, markup=False)
                self.mount(w, before=footer[0]) if footer else self.mount(w)
        else:
            for w in existing:
                w.remove()


class ChatLog(Widget):
    """Renders state.turns. Diff-aware: only mounts new turns; updates last turn in-place."""

    DEFAULT_CSS = "ChatLog { height: 1fr; }"

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Banner(), id="chat-scroll")

    def on_mount(self) -> None:
        self._pending_state: AppState | None = None
        self._sync_scheduled = False
        self.watch(self.app, "app_state", self._on_state_change)
        self.query_one("#chat-scroll", VerticalScroll).anchor()

    def _on_state_change(self, state: AppState) -> None:
        # Coalesce a synchronous batch of store dispatches (a node emits entered →
        # context → thinking → finished with no event-loop yield between them) into a
        # single render per frame. Without this, a NodeCard created in one dispatch is
        # reused in the next before it has composed its children → query_one() raises.
        self._pending_state = state
        if not self._sync_scheduled:
            self._sync_scheduled = True
            self.call_after_refresh(self._flush_sync)

    def _flush_sync(self) -> None:
        self._sync_scheduled = False
        state = self._pending_state
        if state is None:
            return
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
