"""Shared, task-INDEPENDENT validation-check invariants. A 'check' is a runnable
shell command whose exit code decides pass/fail. These functions enforce ONLY what
is true of a well-formed check regardless of the task — never whether the check is
the *right* one (that is the acceptance_critic's semantic, task-dependent job).

Deliberately NOT a command blocklist: banning a shape like `wc -c` would misfire on
a task where a byte count IS the spec (e.g. 'truncate to N bytes')."""
from __future__ import annotations

_PROSE_STARTERS = ("check", "verify", "ensure", "confirm", "make sure",
                   "the ", "it ", "should", "this ", "validate that")


def is_prose(command: str) -> bool:
    low = command.strip().lower()
    return any(low.startswith(p) for p in _PROSE_STARTERS)


def validation_floor_hint(command: str) -> str | None:
    """None if the command clears the task-independent floor; else a fix hint.
    Floor = non-empty AND a runnable command (not prose)."""
    if not command.strip():
        return "is empty; give a runnable shell command."
    if is_prose(command):
        return ("reads as prose, not a runnable command — it is executed literally and "
                "judged by exit code. Give a real shell command (pytest/curl/node -e/diff ...).")
    return None
