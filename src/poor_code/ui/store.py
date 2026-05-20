"""UI state, UI-internal actions, and the Store/reducer.

The Store holds a single immutable AppState. dispatch(action) runs a pure
reducer; subscribers fire on state change. See spec §3.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal

from poor_code.messages import Event


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


Action = Event | UIAction


# =========================================================================
# Reducer — pure function. Cases added incrementally in later tasks.
# =========================================================================


def reduce(state: AppState, action: Action) -> AppState:
    match action:
        case _:
            return state
