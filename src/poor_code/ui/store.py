"""UI state, UI-internal actions, and the Store/reducer.

The Store holds a single immutable AppState. dispatch(action) runs a pure
reducer; subscribers fire on state change. See spec §3.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal

from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    Event,
    NodeEntered,
    PlanReady,
    ProjectMapBuildFailed,
    ProjectMapBuildFinished,
    ProjectMapBuildProgress,
    ProjectMapBuildStarted,
    QueryRaised,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnded,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
)
from poor_code.provider.registry import ModelMeta, lookup


# =========================================================================
# View state — what the UI renders. All frozen.
# =========================================================================


@dataclass(frozen=True)
class ToolCallView:
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    status: Literal["running", "done", "failed"]
    result: Any | None = None
    error: str | None = None


@dataclass(frozen=True)
class TextSegment:
    """A chronological chunk of assistant text. One per agent iteration —
    a new segment starts whenever a ToolCallView interrupts the text flow."""
    text: str


@dataclass(frozen=True)
class NodeLabelSegment:
    """A graph-node boundary header. Streamed text/tools below it belong to this node."""
    node: str
    phase: str


@dataclass(frozen=True)
class QuerySegment:
    prompt: str
    options: tuple[str, ...]
    kind: str


Segment = TextSegment | ToolCallView | NodeLabelSegment | QuerySegment


@dataclass(frozen=True)
class TurnView:
    turn_id: str | None      # None while pending (before TurnStarted arrives)
    cmd_id: str
    user_text: str
    segments: tuple[Segment, ...] = ()
    status: Literal["pending", "running", "done", "failed"] = "pending"
    error: str | None = None
    started_at: float | None = None        # monotonic, set by TurnStarted
    duration_sec: float | None = None      # set by TurnEnded
    model: str | None = None               # set by TurnEnded

    @property
    def assistant_text(self) -> str:
        """Last TextSegment's text — what AssistantMessageCompleted set.
        Kept as a property for tests/callers that just want the final answer."""
        for seg in reversed(self.segments):
            if isinstance(seg, TextSegment):
                return seg.text
        return ""

    @property
    def tool_calls(self) -> tuple[ToolCallView, ...]:
        return tuple(s for s in self.segments if isinstance(s, ToolCallView))


@dataclass(frozen=True)
class UsageState:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class ProjectMapStatus:
    phase: Literal["indexing", "ready", "failed"]
    files_processed: int = 0
    files_total: int = 0
    parse_error_count: int = 0
    duration_ms: int = 0
    error: str | None = None


@dataclass(frozen=True)
class AppState:
    turns: tuple[TurnView, ...] = ()
    is_processing: bool = False
    usage: UsageState = field(default_factory=UsageState)
    last_error: str | None = None
    cwd: str = ""
    provider_name: str | None = None
    model: str | None = None
    model_meta: ModelMeta | None = None
    last_turn_tokens: int = 0
    project_map: ProjectMapStatus | None = None
    awaiting_input: bool = False


# =========================================================================
# UIAction — UI-internal signals. Domain cannot import from this module
# (enforced by lint rule, see spec D8).
# =========================================================================


@dataclass(frozen=True)
class UIAction:
    """Marker base. Concrete UI actions subclass this."""


@dataclass(frozen=True)
class PromptSubmitted(UIAction):
    cmd_id: str
    user_text: str


@dataclass(frozen=True)
class AnswerSubmitted(UIAction):
    turn_id: str
    answer: str


@dataclass(frozen=True)
class CwdChanged(UIAction):
    cwd: str


@dataclass(frozen=True)
class ProviderChanged(UIAction):
    provider_name: str | None
    model: str | None


Action = Event | UIAction


# =========================================================================
# Reducer — pure function. Cases added incrementally in later tasks.
# =========================================================================


# --- internal helpers ---


def _update_turn_at(
    turns: tuple[TurnView, ...], index: int, **changes: Any
) -> tuple[TurnView, ...]:
    new = replace(turns[index], **changes)
    return turns[:index] + (new,) + turns[index + 1 :]


def _find_turn_by_cmd(state: AppState, cmd_id: str) -> int | None:
    for i, t in enumerate(state.turns):
        if t.cmd_id == cmd_id:
            return i
    return None


def _find_turn_by_id(state: AppState, turn_id: str) -> int | None:
    for i, t in enumerate(state.turns):
        if t.turn_id == turn_id:
            return i
    return None


def _replace_segment(
    segments: tuple[Segment, ...], index: int, new: Segment
) -> tuple[Segment, ...]:
    return segments[:index] + (new,) + segments[index + 1 :]


def _update_tool_call(
    state: AppState, turn_id: str, tool_call_id: str, **changes: Any
) -> AppState:
    i = _find_turn_by_id(state, turn_id)
    if i is None:
        return state
    turn = state.turns[i]
    for j, seg in enumerate(turn.segments):
        if isinstance(seg, ToolCallView) and seg.tool_call_id == tool_call_id:
            new_seg = replace(seg, **changes)
            new_segs = _replace_segment(turn.segments, j, new_seg)
            return replace(
                state, turns=_update_turn_at(state.turns, i, segments=new_segs)
            )
    return state


def _append_segment(
    state: AppState, turn_id: str, seg: Segment
) -> AppState:
    i = _find_turn_by_id(state, turn_id)
    if i is None:
        return state
    turn = state.turns[i]
    return replace(
        state,
        turns=_update_turn_at(state.turns, i, segments=turn.segments + (seg,)),
    )


# --- reducer ---


def reduce(state: AppState, action: Action) -> AppState:
    match action:
        case PromptSubmitted(cmd_id=cid, user_text=text):
            new_turn = TurnView(
                turn_id=None, cmd_id=cid, user_text=text, status="pending"
            )
            return replace(
                state, turns=state.turns + (new_turn,), is_processing=True
            )

        case TurnStarted(cmd_id=cid, turn_id=tid):
            i = _find_turn_by_cmd(state, cid)
            if i is None:
                return state
            return replace(
                state,
                turns=_update_turn_at(
                    state.turns, i,
                    turn_id=tid,
                    status="running",
                    started_at=time.monotonic(),
                ),
            )

        case TurnEnded(turn_id=tid, duration_sec=d, model=m):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            return replace(
                state,
                turns=_update_turn_at(
                    state.turns, i,
                    status="done",
                    duration_sec=d,
                    model=m,
                ),
                is_processing=False,
            )

        case TurnFailed(turn_id=tid, error=err):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            turn = state.turns[i]
            duration = (
                time.monotonic() - turn.started_at
                if turn.started_at is not None
                else None
            )
            return replace(
                state,
                turns=_update_turn_at(
                    state.turns, i,
                    status="failed",
                    error=err,
                    duration_sec=duration,
                    model=state.model,
                ),
                is_processing=False,
                last_error=err,
            )

        case AssistantTextDelta(turn_id=tid, text=chunk):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            turn = state.turns[i]
            # Extend the trailing TextSegment, or open a new one if the most
            # recent segment is a tool call (a new iteration's text).
            if turn.segments and isinstance(turn.segments[-1], TextSegment):
                last = turn.segments[-1]
                new_segs = _replace_segment(
                    turn.segments, len(turn.segments) - 1,
                    TextSegment(text=last.text + chunk),
                )
                return replace(
                    state, turns=_update_turn_at(state.turns, i, segments=new_segs)
                )
            return _append_segment(state, tid, TextSegment(text=chunk))

        case AssistantMessageCompleted(turn_id=tid, text=text):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            turn = state.turns[i]
            # Pin the final iteration's text — overwrite the trailing
            # TextSegment if one exists, otherwise append.
            if turn.segments and isinstance(turn.segments[-1], TextSegment):
                new_segs = _replace_segment(
                    turn.segments, len(turn.segments) - 1, TextSegment(text=text),
                )
                return replace(
                    state, turns=_update_turn_at(state.turns, i, segments=new_segs)
                )
            return _append_segment(state, tid, TextSegment(text=text))

        case ToolCallStarted(turn_id=tid, tool_call_id=tcid, tool_name=name, args=args):
            return _append_segment(
                state, tid,
                ToolCallView(tool_call_id=tcid, tool_name=name, args=args, status="running"),
            )

        case ToolCallFinished(turn_id=tid, tool_call_id=tcid, result=r):
            return _update_tool_call(state, tid, tcid, status="done", result=r)

        case ToolCallFailed(turn_id=tid, tool_call_id=tcid, error=err):
            return _update_tool_call(state, tid, tcid, status="failed", error=err)

        case UsageUpdated(input_tokens=i_in, output_tokens=i_out, cost_usd=c):
            return replace(
                state,
                usage=UsageState(
                    input_tokens=state.usage.input_tokens + i_in,
                    output_tokens=state.usage.output_tokens + i_out,
                    cost_usd=state.usage.cost_usd + c,
                ),
                last_turn_tokens=i_in + i_out,
            )

        case ProjectMapBuildStarted(files_total=n):
            return replace(state, project_map=ProjectMapStatus(
                phase="indexing", files_total=n,
            ))

        case ProjectMapBuildProgress(files_processed=p, files_total=n):
            return replace(state, project_map=ProjectMapStatus(
                phase="indexing", files_processed=p, files_total=n,
            ))

        case ProjectMapBuildFinished(files_total=n, parse_error_count=e, duration_ms=d):
            return replace(state, project_map=ProjectMapStatus(
                phase="ready",
                files_processed=n, files_total=n,
                parse_error_count=e, duration_ms=d,
            ))

        case ProjectMapBuildFailed(error=err):
            return replace(state, project_map=ProjectMapStatus(
                phase="failed", error=err,
            ))

        case CwdChanged(cwd=cwd):
            return replace(state, cwd=cwd)

        case ProviderChanged(provider_name=p, model=m):
            meta = lookup(m) if m else None
            return replace(state, provider_name=p, model=m, model_meta=meta)

        case NodeEntered(turn_id=tid, node=node, phase=phase):
            return _append_segment(state, tid, NodeLabelSegment(node=node, phase=phase))

        case QueryRaised(turn_id=tid, kind=kind, prompt=prompt, options=options):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            with_seg = _append_segment(
                state, tid, QuerySegment(prompt=prompt, options=options, kind=kind))
            return replace(with_seg, awaiting_input=True)

        case AnswerSubmitted(turn_id=_tid, answer=_answer):
            if not state.awaiting_input:
                return state
            return replace(state, awaiting_input=False)

        case _:
            return state


# =========================================================================
# Store — single source of truth for UI state. Single asyncio loop.
# =========================================================================


class Store:
    """Holds current AppState; dispatch(action) → reducer → notify listeners."""

    def __init__(self, initial: AppState) -> None:
        self._state = initial
        self._listeners: list[Callable[[AppState], None]] = []

    @property
    def state(self) -> AppState:
        return self._state

    def dispatch(self, action: Action) -> None:
        new = reduce(self._state, action)
        if new is self._state:
            return
        self._state = new
        for listener in list(self._listeners):
            listener(new)

    def subscribe(
        self, listener: Callable[[AppState], None]
    ) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsub() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsub
