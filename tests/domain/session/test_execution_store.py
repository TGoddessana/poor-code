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


def test_changeset_roundtrip(tmp_path):
    from poor_code.domain.session.store import _changeset_to_dict, _dict_to_changeset
    from poor_code.domain.session.models import ChangeSet
    cs = ChangeSet(aggregate_diff="DIFF", per_task=(("t1", "d1"), ("t2", "d2")))
    again = _dict_to_changeset(_changeset_to_dict(cs))
    assert again == cs


def test_write_changeset_writes_file(tmp_path):
    from poor_code.domain.session.store import SessionStore
    from poor_code.domain.session import paths
    from poor_code.domain.session.models import ChangeSet
    store = SessionStore(tmp_path)
    store.write_changeset("sid1", ChangeSet(aggregate_diff="D", per_task=(("t1", "d1"),)))
    p = paths.changeset_json(tmp_path, "sid1")
    assert p.exists()
    import json
    data = json.loads(p.read_text())
    assert data["aggregate_diff"] == "D"
    assert data["per_task"] == [["t1", "d1"]]


def test_write_attempt_artifacts(tmp_path):
    from poor_code.domain.session.store import SessionStore
    from poor_code.domain.session import paths
    from poor_code.domain.session.models import (
        SessionState, Plan, Task, EditScope, Attempt, ChangeRecord, ValidationResult)
    state = SessionState(plan=Plan(tasks=(
        Task(id="t1", title="x", purpose="p", edit_scope=EditScope(editable=("a.txt",)),
             attempts=(Attempt(
                 id="t1-a1",
                 patch=ChangeRecord(files=("a.txt",), diff="--- diff text ---"),
                 run_result=ValidationResult(command="test -f a.txt", exit_code=0,
                                             passed=True, output="ok")),)),)))
    store = SessionStore(tmp_path)
    store.write_attempt_artifacts("sid1", state)
    d = paths.attempt_dir(tmp_path, "sid1", "t1", "t1-a1")
    assert (d / "diff.patch").read_text() == "--- diff text ---"
    import json
    rr = json.loads((d / "run_result.json").read_text())
    assert rr["passed"] is True and rr["exit_code"] == 0


def test_write_attempt_artifacts_skips_empty(tmp_path):
    from poor_code.domain.session.store import SessionStore
    from poor_code.domain.session import paths
    from poor_code.domain.session.models import (
        SessionState, Plan, Task, EditScope, Attempt)
    state = SessionState(plan=Plan(tasks=(
        Task(id="t1", title="x", purpose="p", edit_scope=EditScope(editable=("a.txt",)),
             attempts=(Attempt(id="t1-a1"),)),)))  # no patch, no run_result
    SessionStore(tmp_path).write_attempt_artifacts("sid1", state)
    assert not paths.attempt_dir(tmp_path, "sid1", "t1", "t1-a1").exists()
