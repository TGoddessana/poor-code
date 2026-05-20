"""UI state, UI-internal actions, and the Store/reducer.

The Store holds a single immutable AppState. dispatch(action) runs a pure
reducer; subscribers fire on state change. See spec §3.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal

from poor_code.messages import Event, TurnEnded, TurnFailed, TurnStarted


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
class TurnView:
    turn_id: str | None      # None while pending (before TurnStarted arrives)
    cmd_id: str
    user_text: str
    assistant_text: str = ""
    tool_calls: tuple[ToolCallView, ...] = ()
    status: Literal["pending", "running", "done", "failed"] = "pending"
    error: str | None = None


@dataclass(frozen=True)
class UsageState:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class AppState:
    turns: tuple[TurnView, ...] = ()
    is_processing: bool = False
    usage: UsageState = field(default_factory=UsageState)
    last_error: str | None = None
    cwd: str = ""


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
                state, turns=_update_turn_at(state.turns, i, turn_id=tid, status="running")
            )

        case TurnEnded(turn_id=tid):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            return replace(
                state,
                turns=_update_turn_at(state.turns, i, status="done"),
                is_processing=False,
            )

        case TurnFailed(turn_id=tid, error=err):
            i = _find_turn_by_id(state, tid)
            if i is None:
                return state
            return replace(
                state,
                turns=_update_turn_at(state.turns, i, status="failed", error=err),
                is_processing=False,
                last_error=err,
            )

        case _:
            return state
