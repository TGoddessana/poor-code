"""Render user steering directives for injection into node prompts. Used by
AgentNode._dispatch and the hand-rolled LLM nodes (implementer, provisioner,
fast_path) so a mid-turn interrupt's steering reaches every model call."""
from __future__ import annotations

STEERING_HEADER = "[User steering — honor these directives over earlier plans]"
DRIVER_FEEDBACK_HEADER = "[Smart Driver feedback — apply this to this node invocation]"


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


def _feedback_packets_for(state, node: str):
    control = getattr(state, "driver_control", None)
    packets = getattr(control, "feedback_packets", ()) if control is not None else ()
    return tuple(
        p for p in packets
        if node in getattr(p, "target_nodes", ()) or "*" in getattr(p, "target_nodes", ())
    )


def _render_packet(packet) -> str:
    parts: list[str] = []
    summary = getattr(packet, "summary", "")
    instruction = getattr(packet, "instruction", "")
    evidence = tuple(getattr(packet, "evidence", ()) or ())
    if summary:
        parts.append(f"Summary: {summary}")
    if evidence:
        parts.append("Evidence:")
        parts.extend(f"- {item}" for item in evidence)
    if instruction:
        parts.append(f"Instruction: {instruction}")
    return "\n".join(parts)


def driver_feedback_message(state, node: str) -> dict | None:
    packets = _feedback_packets_for(state, node)
    if not packets:
        return None
    rendered = "\n\n".join(_render_packet(p) for p in packets if _render_packet(p))
    if not rendered:
        return None
    return {"role": "user", "content": f"{DRIVER_FEEDBACK_HEADER}\n{rendered}"}


def driver_feedback_block(state, node: str) -> str:
    packets = _feedback_packets_for(state, node)
    if not packets:
        return ""
    rendered = "\n\n".join(_render_packet(p) for p in packets if _render_packet(p))
    if not rendered:
        return ""
    return f"\n{DRIVER_FEEDBACK_HEADER}\n{rendered}"
