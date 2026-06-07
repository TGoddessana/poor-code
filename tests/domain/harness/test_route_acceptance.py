from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    AcceptanceSpec, Layer, Requirement, SessionState, Verdict, VerdictKind,
)


def test_interviewer_now_forwards_to_acceptance_oracle():
    res = NodeResult(output=Requirement(summary="x"))
    assert route("interviewer", res, SessionState()) == "acceptance_oracle"


def test_oracle_forwards_to_acceptance_gate():
    res = NodeResult(output=AcceptanceSpec())
    assert route("acceptance_oracle", res, SessionState()) == "acceptance_gate"


def test_gate_advance_forwards_to_critic():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("acceptance_gate", res, SessionState()) == "acceptance_critic"


def test_critic_advance_forwards_to_spec_confirm_gate():
    # acceptance_critic now routes through spec_confirm_gate before planner
    res = NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
    assert route("acceptance_critic", res, SessionState()) == "spec_confirm_gate"


def test_acceptance_repair_loops_back_to_oracle():
    res = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.ACCEPTANCE))
    assert route("acceptance_gate", res, SessionState()) == "acceptance_oracle"
    assert route("acceptance_critic", res, SessionState()) == "acceptance_oracle"
