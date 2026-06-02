from poor_code.domain.session.store import _attempt_to_dict, _dict_to_attempt
from poor_code.domain.session.models import (
    Attempt, AttemptStatus, ChangeRecord, ValidationResult, Verdict, VerdictKind, Layer,
)


def test_attempt_roundtrip_full():
    a = Attempt(
        id="a1",
        patch=ChangeRecord(files=("f.py",), diff="@@"),
        assumptions=("x",),
        validator_verdict=Verdict(kind=VerdictKind.ADVANCE),
        run_result=ValidationResult(command="pytest -q", exit_code=1, passed=False, output="boom"),
        gate_verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION, hint="retry"),
        adversarial_rounds=2,
        status=AttemptStatus.ACTIVE,
    )
    back = _dict_to_attempt(_attempt_to_dict(a))
    assert back == a


def test_attempt_roundtrip_minimal():
    a = Attempt(id="a2")
    assert _dict_to_attempt(_attempt_to_dict(a)) == a


from poor_code.domain.session.store import _session_state_to_dict, _dict_to_session_state
from poor_code.domain.session.models import SessionState, FeedbackEntry
from pathlib import Path


def test_session_state_roundtrips_feedback():
    s = SessionState().with_feedback_entry(
        FeedbackEntry(failure_type="import", symptom="X", prevention_hint="Y", task_ref="t1")
    )
    back = _dict_to_session_state(_session_state_to_dict(s), Path("x"))
    assert back.feedback.entries == s.feedback.entries
