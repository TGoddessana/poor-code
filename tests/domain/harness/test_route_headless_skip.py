"""Headless (FULL_AUTO) skips the human-dialogue interviewer and the LLM plan
reviewer.

Why this exists: the interviewer needs a human to answer; unattended it only burns
round-trips, so FULL_AUTO skips it. With the acceptance oracle/gate/critic removed
(experiment), there is no longer a lean-acceptance node to land on, so in FULL_AUTO
the understanding_gate ADVANCE routes straight to the planner: interviewer is skipped
(downstream nodes use effective_requirement(state), synthesizing the requirement from
the request text) and spec_confirm_gate is skipped (no human to confirm). The plan
reviewer and plan_confirm_gate are likewise skipped. SUPERVISED (TUI) is unchanged:
the human answers the interviewer and confirms the spec.
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


def test_full_auto_understanding_gate_skips_interviewer_to_planner():
    # Headless: skip the human-dialogue interviewer; no acceptance node to land on, so
    # go straight to the planner (which synthesizes the requirement from the request).
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("understanding_gate", _advance(), state) == "planner"


def test_supervised_interviewer_forwards_to_spec_confirm_gate():
    # TUI: the human confirms the spec after the interview.
    from poor_code.domain.session.models import Requirement
    state = SessionState(policy=Policy.SUPERVISED)
    res = NodeResult(output=Requirement(summary="x"))
    assert route("interviewer", res, state) == "spec_confirm_gate"


def test_supervised_plan_gate_advances_to_plan_reviewer():
    # TUI: the decomposition critic runs after the structural gate.
    state = SessionState(policy=Policy.SUPERVISED)
    assert route("plan_gate", _advance(), state) == "plan_reviewer"


def test_full_auto_plan_gate_skips_reviewer_to_provisioner():
    # Headless: the weak LLM plan critic diverges (false-positive replans → burns the
    # latency budget — weak-verifier-divergence, 2404.17140). Skip it; the deterministic
    # PlanGate (the strong verifier) already passed.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("plan_gate", _advance(), state) == "provisioner"


def test_full_auto_does_not_alter_unrelated_edges():
    # The redirects are surgical: interviewer entry, spec_confirm_gate, and the plan
    # reviewer/plan_confirm_gate move; nothing else.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("plan_reviewer", _advance(), state) == "provisioner"
    assert route("provisioner", _advance(), state) == "implement_loop"


def test_full_auto_understanding_repair_still_loops_to_explorer():
    # Skipping the interview must not break the understanding-layer back-edge.
    state = SessionState(policy=Policy.FULL_AUTO)
    from poor_code.domain.session.models import Layer
    res = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.UNDERSTANDING))
    assert route("understanding_gate", res, state) == "explorer"


def test_full_auto_skips_plan_confirm_gate_to_provisioner():
    # In FULL_AUTO, plan_reviewer (when reached under SUPERVISED) would normally
    # forward to plan_confirm_gate; the remap skips it straight to provisioner.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("plan_reviewer", _advance(), state) == "provisioner"


def test_full_auto_skips_interviewer_and_confirm_gates():
    # Direct remap entries exist in _FULL_AUTO_SKIP.
    from poor_code.domain.harness.route import _FULL_AUTO_SKIP
    assert _FULL_AUTO_SKIP.remap["interviewer"] == "planner"
    assert _FULL_AUTO_SKIP.remap["spec_confirm_gate"] == "planner"
    assert _FULL_AUTO_SKIP.remap["plan_confirm_gate"] == "provisioner"
