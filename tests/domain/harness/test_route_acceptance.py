"""Routing after the acceptance oracle/gate/critic were removed (experiment).
The interviewer now forwards straight to spec_confirm_gate, and a Layer.ACCEPTANCE
repair (emitted only by spec_confirm_gate on a SUPERVISED rejection) bounces to the
interviewer — the spec's author now that the oracle is gone."""
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    Layer, Requirement, SessionState, Verdict, VerdictKind,
)


def test_interviewer_forwards_to_spec_confirm_gate():
    res = NodeResult(output=Requirement(summary="x"))
    assert route("interviewer", res, SessionState()) == "spec_confirm_gate"


def test_spec_confirm_gate_advance_forwards_to_planner():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("spec_confirm_gate", res, SessionState()) == "planner"


def test_acceptance_repair_bounces_to_interviewer():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.ACCEPTANCE))
    assert route("spec_confirm_gate", res, SessionState()) == "interviewer"
