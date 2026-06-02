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


from poor_code.domain.session.store import _verdict_to_dict, _dict_to_verdict
from poor_code.domain.session.models import Verdict, VerdictKind


def test_verdict_query_roundtrips():
    v = Verdict(kind=VerdictKind.ESCALATE, query="need human input")
    assert _dict_to_verdict(_verdict_to_dict(v)) == v


from poor_code.domain.session.store import SessionStore
from poor_code.domain.session.models import (
    Plan, Task, Cursor, Phase, Attempt, AttemptStatus, ValidationResult,
)


def test_store_roundtrips_plan_with_attempts(tmp_path):
    store = SessionStore(tmp_path)
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p", how_to_validate="true"),))
    s = (SessionState(plan=plan,
                      cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer"))
         .with_active_task("t1")
         .append_attempt("t1", Attempt(
             id="a1",
             run_result=ValidationResult(command="true", exit_code=0, passed=True),
             status=AttemptStatus.DONE)))
    store.write_session_state("sid", s)
    back = store.read_session_state("sid")
    assert back == s
