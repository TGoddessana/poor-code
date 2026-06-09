"""Render user steering directives for injection into node prompts. Used by
AgentNode._dispatch and the hand-rolled LLM nodes (implementer, provisioner,
fast_path) so a mid-turn interrupt's steering reaches every model call."""
from __future__ import annotations

STEERING_HEADER = "[User steering — honor these directives over earlier plans]"


def _joined(notes: tuple[str, ...]) -> str:
    return "\n".join(f"- {s}" for s in notes)


def steering_message(notes: tuple[str, ...]) -> dict | None:
    """A chat 'user' message for nodes that build a messages list. None when empty."""
    if not notes:
        return None
    return {"role": "user", "content": f"{STEERING_HEADER}\n{_joined(notes)}"}


def steering_block(notes: tuple[str, ...]) -> str:
    """A plain-text block ('' when empty) to append to an existing prompt STRING."""
    if not notes:
        return ""
    return f"\n{STEERING_HEADER}\n{_joined(notes)}"
