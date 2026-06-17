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
    ("interviewer", None): "spec_confirm_gate",  # acceptance oracle/gate/critic removed (experiment)
    ("spec_confirm_gate", None): "planner",
    ("planner", None): "plan_gate",
    ("plan_gate", None): "plan_reviewer",          # gate ADVANCE falls through here
    ("plan_reviewer", None): "plan_confirm_gate",  # reviewer ADVANCE falls through here
    ("plan_confirm_gate", None): "provisioner",
    ("provisioner", None): "implement_loop",       # bootstrap env, then enter the impl subgraph
    # The whole task-execution loop is folded into the implement_loop subgraph; its
    # inner edges live in subgraphs/implement_loop.py, not here. It exits 'done' when
    # task_selector has no more runnable tasks.
    ("implement_loop", "done"): "global_validator",
    ("global_validator", "pass"): "reporter",
}

# back-edge target per broken layer (fail-to-shallowest, design.md §6/§18).
# Layer.ACCEPTANCE used to bounce to the acceptance_oracle (now removed). The only
# remaining emitter is spec_confirm_gate: a SUPERVISED user rejecting the spec. The
# spec is now just the Requirement, so a rejection bounces to the interviewer (its
# author) to revise it, rather than escaping the whole run.
_SHALLOWEST: dict[Layer, str] = {
    Layer.IMPLEMENTATION: "implement_loop",   # re-enter the execution subgraph (implementer lives inside)
    Layer.PLAN: "planner",
    Layer.UNDERSTANDING: "explorer",
    Layer.ACCEPTANCE: "interviewer",
}

# FULL_AUTO (headless): no human to answer the interviewer, so skip that node — it
# would only auto-answer "use your best judgment" and burn round-trips. With the
# acceptance oracle/gate/critic removed (experiment), the headless path runs straight
# from understanding to the planner: interviewer is skipped (nodes downstream use
# effective_requirement(state), which synthesizes the requirement from the request
# text when state.requirement is absent), and spec_confirm_gate is skipped (no human
# to confirm). The per-task Verifier grounds 'done' on req.acceptance + the request.
# FULL_AUTO also skips the LLM plan_reviewer: a weak self-verifier diverges via
# false-positive replans (2404.17140 weak-verifier-divergence — the report's load-
# bearing finding) and each pass is a full LLM call against the latency wall. The
# deterministic PlanGate (a strong, exact verifier) already ran; decomposition-quality
# judgement is exactly where the weak critic hurts. SUPERVISED keeps it (human present).
_FULL_AUTO_SKIP = Rewrite(
    when=lambda s: s.policy is Policy.FULL_AUTO,
    remap={"interviewer": "planner", "spec_confirm_gate": "planner",
           "plan_reviewer": "provisioner", "plan_confirm_gate": "provisioner"},
)

DEFAULT_EDGES = EdgeTable(
    forward=FORWARD,
    back_edges=_SHALLOWEST,
    rewrites=(_FULL_AUTO_SKIP,),
)


def route(node: str, result: NodeResult, state: SessionState) -> str | None:
    """하위호환 진입점 — 진입 그래프의 EdgeTable.route 로 위임."""
    return DEFAULT_EDGES.route(node, result, state)
