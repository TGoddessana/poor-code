"""Headless (FULL_AUTO) skips the human-dialogue interviewer and the adequacy
critic, but KEEPS a lean acceptance (oracle + gate) grounded in the issue text.

Why this exists: the interviewer needs a human to answer; unattended it only burns
round-trips, so FULL_AUTO skips it. But the acceptance_oracle does NOT need a human —
it grounds its global done-check on the request/issue text (which headless HAS), and
that check is the independent witness that defends "small tasks pass => issue
resolved" (the per-task how_to_validate is self-authored and self-confirming). So in
FULL_AUTO the understanding_gate ADVANCE routes to acceptance_oracle (not the
interviewer), runs the deterministic gate, then skips the expensive LLM adequacy
critic straight to the planner. This re-activates the global_validator->planner
corrective cycle that the earlier skip-everything had killed. SUPERVISED (TUI) is
unchanged: the human answers the interviewer and the full critic runs.
"""
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    Policy, SessionState, Verdict, VerdictKind,
)


def _advance() -> NodeResult:
    return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))


def test_supervised_understanding_gate_advances_to_interviewer():
    # TUI default: human present → full interview runs.
    state = SessionState(policy=Policy.SUPERVISED)
    assert route("understanding_gate", _advance(), state) == "interviewer"


def test_full_auto_understanding_gate_skips_interviewer_to_acceptance_oracle():
    # Headless: skip the human-dialogue interviewer, but still run the oracle so the
    # issue-grounded independent done-check exists.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("understanding_gate", _advance(), state) == "acceptance_oracle"


def test_supervised_acceptance_gate_advances_to_critic():
    # TUI: the adversarial adequacy critic runs after the gate.
    state = SessionState(policy=Policy.SUPERVISED)
    assert route("acceptance_gate", _advance(), state) == "acceptance_critic"


def test_full_auto_acceptance_gate_skips_critic_to_planner():
    # Headless: keep oracle+gate (independent check + well-formedness floor) but skip
    # the expensive LLM adequacy critic — grounding on the issue does the adequacy work.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("acceptance_gate", _advance(), state) == "planner"


def test_supervised_plan_gate_advances_to_plan_reviewer():
    # TUI: the decomposition critic runs after the structural gate.
    state = SessionState(policy=Policy.SUPERVISED)
    assert route("plan_gate", _advance(), state) == "plan_reviewer"


def test_full_auto_plan_gate_skips_reviewer_to_provisioner():
    # Headless: the weak LLM plan critic diverges (false-positive replans → burns the
    # latency budget — weak-verifier-divergence, 2404.17140). Skip it; the deterministic
    # PlanGate (the strong verifier) already passed. Mirrors the acceptance_critic skip.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("plan_gate", _advance(), state) == "provisioner"


def test_full_auto_does_not_alter_unrelated_edges():
    # The redirects are surgical: interviewer entry, the acceptance critic, and the
    # plan reviewer move; nothing else.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("plan_reviewer", _advance(), state) == "provisioner"
    assert route("acceptance_oracle", _advance(), state) == "acceptance_gate"
    assert route("provisioner", _advance(), state) == "implement_loop"


def test_full_auto_understanding_repair_still_loops_to_explorer():
    # Skipping the interview must not break the understanding-layer back-edge.
    state = SessionState(policy=Policy.FULL_AUTO)
    from poor_code.domain.session.models import Layer
    res = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.UNDERSTANDING))
    assert route("understanding_gate", res, state) == "explorer"
