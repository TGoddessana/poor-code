# src/poor_code/domain/harness/route.py
"""The graph's edges live HERE and nowhere else. Forward edges are data
(FORWARD); back-edges are logic (route()). Nodes never know their neighbors."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import (
    Layer, Policy, Request, SessionState, VerdictKind,
)

# (node_name, branch) → next_node. branch=None for single-out nodes.
FORWARD: dict[tuple[str, str | None], str] = {
    ("router", "engineering"): "explorer",
    ("router", "lightweight"): "fast_path",
    ("explorer", None): "understanding_gate",
    ("understanding_gate", None): "interviewer",  # gate ADVANCE falls through here
    ("interviewer", None): "acceptance_oracle",
    ("acceptance_oracle", None): "acceptance_gate",
    ("acceptance_gate", None): "acceptance_critic",  # gate ADVANCE falls through here
    ("acceptance_critic", None): "planner",          # critic ADVANCE falls through here
    ("planner", None): "plan_gate",
    ("plan_gate", None): "plan_reviewer",          # gate ADVANCE falls through here
    ("plan_reviewer", None): "task_selector",      # reviewer ADVANCE falls through here
    ("task_selector", "task"): "composer",
    ("task_selector", "done"): "global_validator",
    ("composer", None): "implementer",
    ("implementer", None): "eng_gate",
    ("eng_gate", None): "validator",
    ("validator", None): "validation_runner",
    ("validation_runner", "pass"): "completion_gate",
    ("validation_runner", "fail"): "failure_analyst",
    ("failure_analyst", None): "completion_gate",
    ("completion_gate", "done"): "task_selector",
    ("global_validator", "pass"): "reporter",
}

# back-edge target per broken layer (fail-to-shallowest, design.md §6/§18).
_SHALLOWEST: dict[Layer, str] = {
    Layer.IMPLEMENTATION: "implementer",
    Layer.PLAN: "planner",
    Layer.UNDERSTANDING: "explorer",
    Layer.ACCEPTANCE: "acceptance_oracle",
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
    branch = result.branch if result.branch is not None else _branch(node, result)
    nxt = FORWARD.get((node, branch))
    # FULL_AUTO (headless) has no human to answer the interviewer or to add signal
    # to the acceptance spec, so that whole layer only burns LLM round-trips against
    # the wall-clock. Skip it: understanding_gate ADVANCE jumps straight to the
    # planner, and since the interview→acceptance→planner chain is linear and only
    # entered here, none of those nodes are ever reached. The planner synthesizes
    # its requirement from the raw request when state.requirement is absent.
    if state.policy is Policy.FULL_AUTO and nxt == "interviewer":
        return "planner"
    return nxt
