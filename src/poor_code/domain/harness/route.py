# src/poor_code/domain/harness/route.py
"""The graph's edges live HERE and nowhere else. Forward edges are data
(FORWARD); back-edges are logic (route()). Nodes never know their neighbors."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import (
    Layer, Request, SessionState, VerdictKind,
)

# (node_name, branch) → next_node. branch=None for single-out nodes.
FORWARD: dict[tuple[str, str | None], str] = {
    ("router", "engineering"): "locator",
    ("router", "lightweight"): "fast_path",
    ("locator", None): "understanding_gate",
    ("understanding_gate", None): "interviewer",  # gate ADVANCE falls through here
    ("interviewer", None): "planner",             # done → planner (unregistered → park)
}

# back-edge target per broken layer (fail-to-shallowest, design.md §6/§18).
_SHALLOWEST: dict[Layer, str] = {
    Layer.IMPLEMENTATION: "implementer",
    Layer.PLAN: "planner",
    Layer.UNDERSTANDING: "locator",
}


def _branch(node: str, result: NodeResult) -> str | None:
    if node == "router" and isinstance(result.output, Request):
        return result.output.kind.value
    return None


def route(node: str, result: NodeResult, state: SessionState) -> str | None:
    """Next node name, or None to STOP (terminal). A returned name that the
    registry doesn't know = park (Driver handles it)."""
    v = result.verdict
    if v is not None:
        if v.kind is VerdictKind.REPAIR and v.layer is not None:
            return _SHALLOWEST[v.layer]
        if v.kind is VerdictKind.ESCALATE:
            return "user"
    return FORWARD.get((node, _branch(node, result)))
