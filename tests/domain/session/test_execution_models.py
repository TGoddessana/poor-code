from poor_code.domain.session.models import Phase


def test_phase_has_execution_values():
    assert Phase.IMPLEMENTING.value == "implementing"
    assert Phase.FINALIZING.value == "finalizing"


from poor_code.domain.session.models import (
    AttemptStatus, ValidationResult, ChangeRecord,
    FeedbackEntry, FeedbackMemory, ChangeSet, SelectedTask,
)


def test_validation_result_passed_field():
    r = ValidationResult(command="pytest -q", exit_code=0, passed=True, output="ok")
    assert r.passed is True and r.exit_code == 0


def test_change_record_defaults_empty():
    c = ChangeRecord()
    assert c.files == () and c.diff == ""


def test_feedback_memory_holds_entries():
    e = FeedbackEntry(failure_type="import", symptom="ModuleNotFound",
                      prevention_hint="add to deps", task_ref="t1")
    mem = FeedbackMemory(entries=(e,))
    assert mem.entries[0].prevention_hint == "add to deps"


def test_changeset_per_task_pairs():
    cs = ChangeSet(aggregate_diff="d", per_task=(("t1", "diff1"),))
    assert cs.per_task[0] == ("t1", "diff1")


def test_selected_task_carries_id():
    assert SelectedTask(task_id="t1").task_id == "t1"


def test_attempt_status_values():
    assert AttemptStatus.ACTIVE.value == "active"
    assert AttemptStatus.DONE.value == "done"
    assert AttemptStatus.ABANDONED.value == "abandoned"


from poor_code.domain.session.models import Attempt, Verdict, VerdictKind


def test_attempt_defaults():
    a = Attempt(id="a1")
    assert a.id == "a1"
    assert a.patch is None
    assert a.run_result is None
    assert a.validator_verdict is None
    assert a.gate_verdict is None
    assert a.adversarial_rounds == 0
    assert a.status == AttemptStatus.ACTIVE
    assert a.assumptions == ()


def test_attempt_carries_run_result():
    rr = ValidationResult(command="true", exit_code=0, passed=True)
    a = Attempt(id="a1", run_result=rr, status=AttemptStatus.DONE)
    assert a.run_result.passed is True and a.status == AttemptStatus.DONE


from poor_code.domain.session.models import SessionState


def test_session_state_feedback_starts_empty():
    assert SessionState().feedback.entries == ()


def test_with_feedback_entry_appends_immutably():
    s0 = SessionState()
    e = FeedbackEntry(failure_type="x", symptom="y", prevention_hint="z")
    s1 = s0.with_feedback_entry(e)
    assert s0.feedback.entries == ()          # original untouched
    assert s1.feedback.entries == (e,)
