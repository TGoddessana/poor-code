from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Layer, SessionState,
)


def test_acceptance_spec_holds_checks():
    spec = AcceptanceSpec(checks=(
        AcceptanceCheck(criterion="file content", command="diff - hello.txt", rationale="r"),
    ))
    assert spec.checks[0].criterion == "file content"
    assert spec.checks[0].command == "diff - hello.txt"


def test_with_acceptance_round_trips():
    spec = AcceptanceSpec(checks=(AcceptanceCheck(criterion="c", command="true"),))
    s = SessionState().with_acceptance(spec)
    assert s.acceptance is spec
    assert SessionState().acceptance is None


def test_layer_has_acceptance():
    assert Layer.ACCEPTANCE.value == "acceptance"


def test_driver_apply_writes_acceptance():
    spec = AcceptanceSpec(checks=(AcceptanceCheck(criterion="c", command="true"),))
    out = Driver._apply(SessionState(), NodeResult(output=spec))
    assert out.acceptance is spec
