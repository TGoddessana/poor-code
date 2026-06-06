# src/poor_code/domain/harness/route.py
"""The graph's edges live HERE and nowhere else. Forward edges are data
(FORWARD); back-edges are data (_SHALLOWEST); policy rewrites (_FULL_AUTO_SKIP)
handle conditional skips. All assembled into DEFAULT_EDGES; route() delegates to it.
Nodes never know their neighbors."""
from __future__ import annotations

from poor_code.domain.harness.graph import EdgeTable, Rewrite
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import Layer, Policy, SessionState

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
    ("plan_reviewer", None): "provisioner",        # reviewer ADVANCE falls through here
    ("provisioner", None): "implement_loop",       # bootstrap env, then enter the impl subgraph
    # The whole task-execution loop is folded into the implement_loop subgraph; its
    # inner edges live in subgraphs/implement_loop.py, not here. It exits 'done' when
    # task_selector has no more runnable tasks.
    ("implement_loop", "done"): "global_validator",
    ("global_validator", "pass"): "reporter",
}

# back-edge target per broken layer (fail-to-shallowest, design.md §6/§18).
_SHALLOWEST: dict[Layer, str] = {
    Layer.IMPLEMENTATION: "implement_loop",   # re-enter the execution subgraph (implementer lives inside)
    Layer.PLAN: "planner",
    Layer.UNDERSTANDING: "explorer",
    Layer.ACCEPTANCE: "acceptance_oracle",
}

# FULL_AUTO (headless): no human to answer the interviewer, so skip that node — it
# would only auto-answer "use your best judgment" and burn round-trips. But KEEP a
# lean acceptance: the acceptance_oracle grounds its global done-check on the issue
# text (request.raw_text, which carries the reproduction), and that check is the
# independent witness that defends "all per-task validations pass => issue resolved"
# (the per-task how_to_validate is self-authored by the same model that writes the
# fix, so it is self-confirming). We drop only the human-dialogue interviewer and the
# expensive LLM adequacy critic; the oracle + deterministic gate stay, re-activating
# the global_validator->planner corrective cycle. acceptance_oracle (like the planner)
# synthesizes its requirement from the request when state.requirement is absent.
# Mirrors the old inline route() special-case exactly.
# FULL_AUTO also skips the LLM plan_reviewer: a weak self-verifier diverges via
# false-positive replans (2404.17140 weak-verifier-divergence — the report's load-
# bearing finding) and each pass is a full LLM call against the latency wall. The
# deterministic PlanGate (a strong, exact verifier) already ran; decomposition-quality
# judgement is exactly where the weak critic hurts. SUPERVISED keeps it (human present).
_FULL_AUTO_SKIP = Rewrite(
    when=lambda s: s.policy is Policy.FULL_AUTO,
    remap={"interviewer": "acceptance_oracle", "acceptance_critic": "planner",
           "plan_reviewer": "provisioner"},
)

DEFAULT_EDGES = EdgeTable(
    forward=FORWARD,
    back_edges=_SHALLOWEST,
    rewrites=(_FULL_AUTO_SKIP,),
)


def route(node: str, result: NodeResult, state: SessionState) -> str | None:
    """하위호환 진입점 — 진입 그래프의 EdgeTable.route 로 위임."""
    return DEFAULT_EDGES.route(node, result, state)
