"""Headless (FULL_AUTO) skips the interview + acceptance layer.

Why this exists: the interviewer + acceptance(oracle/gate/critic) nodes only add
signal when a human answers their questions. Unattended (FULL_AUTO) they auto-answer
"use your best judgment" and burn LLM round-trips against the bench wall-clock —
the dominant blocker. So in FULL_AUTO the understanding_gate ADVANCE routes straight
to the planner, and the acceptance chain is never entered. SUPERVISED (TUI) is
unchanged: a human is present to answer, so the full interview runs.
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


def test_full_auto_understanding_gate_skips_interview_to_planner():
    # Headless: no human → skip the interview/acceptance ceremony entirely.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("understanding_gate", _advance(), state) == "planner"


def test_full_auto_does_not_alter_unrelated_edges():
    # The redirect is surgical: only the interview entry point moves.
    state = SessionState(policy=Policy.FULL_AUTO)
    assert route("plan_gate", _advance(), state) == "plan_reviewer"
    assert route("plan_reviewer", _advance(), state) == "task_selector"


def test_full_auto_understanding_repair_still_loops_to_explorer():
    # Skipping the interview must not break the understanding-layer back-edge.
    state = SessionState(policy=Policy.FULL_AUTO)
    from poor_code.domain.session.models import Layer
    res = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.UNDERSTANDING))
    assert route("understanding_gate", res, state) == "explorer"
