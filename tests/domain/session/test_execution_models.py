import pytest

from poor_code.domain.session.models import (
    Attempt,
    AttemptStatus,
    ChangeRecord,
    ChangeSet,
    Cursor,
    FeedbackEntry,
    FeedbackMemory,
    Phase,
    Plan,
    SelectedTask,
    SessionState,
    Task,
    TaskStatus,
    ValidationResult,
    Verdict,
    VerdictKind,
)


def test_phase_has_execution_values():
    assert Phase.IMPLEMENTING.value == "implementing"
    assert Phase.FINALIZING.value == "finalizing"


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


def test_session_state_feedback_starts_empty():
    assert SessionState().feedback.entries == ()


def test_with_feedback_entry_appends_immutably():
    s0 = SessionState()
    e = FeedbackEntry(failure_type="x", symptom="y", prevention_hint="z")
    s1 = s0.with_feedback_entry(e)
    assert s0.feedback.entries == ()          # original untouched
    assert s1.feedback.entries == (e,)


def _state_with_two_tasks():
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p"),
                       Task(id="t2", title="B", purpose="p")))
    cur = Cursor(phase=Phase.IMPLEMENTING, current_node="task_selector")
    return SessionState(plan=plan, cursor=cur)


def test_with_active_task_sets_status_and_cursor():
    s = _state_with_two_tasks().with_active_task("t2")
    t2 = [t for t in s.plan.tasks if t.id == "t2"][0]
    assert t2.status == TaskStatus.ACTIVE
    assert s.cursor.task_id == "t2"
    # Fix 2: active_task_id must stay in sync with cursor.task_id
    assert s.active_task_id == "t2"


def test_with_task_status_changes_one_task():
    s = _state_with_two_tasks().with_task_status("t1", TaskStatus.DONE)
    by_id = {t.id: t for t in s.plan.tasks}
    assert by_id["t1"].status == TaskStatus.DONE
    assert by_id["t2"].status == TaskStatus.PENDING


def test_append_attempt_adds_and_sets_cursor():
    s = _state_with_two_tasks().with_active_task("t1")
    s = s.append_attempt("t1", Attempt(id="a1"))
    t1 = [t for t in s.plan.tasks if t.id == "t1"][0]
    assert len(t1.attempts) == 1 and t1.attempts[0].id == "a1"
    assert s.cursor.attempt_id == "a1"


def test_update_attempt_attaches_run_result():
    s = _state_with_two_tasks().with_active_task("t1").append_attempt("t1", Attempt(id="a1"))
    rr = ValidationResult(command="true", exit_code=0, passed=True)
    s = s.update_attempt("t1", "a1", run_result=rr, status=AttemptStatus.DONE)
    a = [t for t in s.plan.tasks if t.id == "t1"][0].attempts[0]
    assert a.run_result.passed is True and a.status == AttemptStatus.DONE


from poor_code.domain.session.models import TaskCompleted


def test_task_completed_carries_ids():
    tc = TaskCompleted(task_id="t1", attempt_id="a1")
    assert tc.task_id == "t1" and tc.attempt_id == "a1"


# Fix 1: unknown task_id raises ValueError

def test_with_active_task_unknown_id_raises():
    s = _state_with_two_tasks()
    with pytest.raises(ValueError, match="task 'nope' not found in plan"):
        s.with_active_task("nope")


def test_with_task_status_unknown_id_raises():
    s = _state_with_two_tasks()
    with pytest.raises(ValueError, match="task 'nope' not found in plan"):
        s.with_task_status("nope", TaskStatus.DONE)


def test_append_attempt_unknown_task_raises():
    s = _state_with_two_tasks()
    with pytest.raises(ValueError, match="task 'nope' not found in plan"):
        s.append_attempt("nope", Attempt(id="a1"))


def test_update_attempt_unknown_task_raises():
    s = _state_with_two_tasks().with_active_task("t1").append_attempt("t1", Attempt(id="a1"))
    with pytest.raises(ValueError, match="task 'nope' not found in plan"):
        s.update_attempt("nope", "a1")


def test_update_attempt_unknown_attempt_raises():
    s = _state_with_two_tasks().with_active_task("t1").append_attempt("t1", Attempt(id="a1"))
    with pytest.raises(ValueError, match="attempt 'nope' not found in task 't1'"):
        s.update_attempt("t1", "nope")


def _state_with_one_task():
    from poor_code.domain.session.models import (
        SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus)
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("a.txt",)),
                              how_to_validate="test -f a.txt", status=TaskStatus.ACTIVE),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="composer", task_id="t1"))


def test_with_task_context_sets_context():
    from poor_code.domain.session.models import TaskContext, CodeRef
    st = _state_with_one_task()
    ctx = TaskContext(refs=(CodeRef(file="a.txt"),), snippet=None)
    st2 = st.with_task_context("t1", ctx)
    assert st2.plan.tasks[0].context == ctx
    assert st.plan.tasks[0].context is None  # original untouched (frozen)


def test_with_task_context_unknown_task_raises():
    st = _state_with_one_task()
    from poor_code.domain.session.models import TaskContext
    import pytest
    with pytest.raises(ValueError):
        st.with_task_context("nope", TaskContext())


def test_upsert_attempt_appends_when_id_new():
    from poor_code.domain.session.models import Attempt
    st = _state_with_one_task()
    st2 = st.upsert_attempt("t1", Attempt(id="t1-a1"))
    assert len(st2.plan.tasks[0].attempts) == 1
    assert st2.cursor.attempt_id == "t1-a1"


def test_upsert_attempt_replaces_when_id_exists():
    from poor_code.domain.session.models import Attempt, ChangeRecord
    st = _state_with_one_task().upsert_attempt("t1", Attempt(id="t1-a1", adversarial_rounds=0))
    st2 = st.upsert_attempt(
        "t1", Attempt(id="t1-a1", adversarial_rounds=1,
                      patch=ChangeRecord(files=("a.txt",), diff="d")))
    assert len(st2.plan.tasks[0].attempts) == 1            # replaced, not appended
    assert st2.plan.tasks[0].attempts[0].adversarial_rounds == 1
    assert st2.plan.tasks[0].attempts[0].patch.files == ("a.txt",)
    assert st2.cursor.attempt_id == "t1-a1"


def test_upsert_attempt_unknown_task_raises():
    from poor_code.domain.session.models import Attempt
    import pytest
    with pytest.raises(ValueError):
        _state_with_one_task().upsert_attempt("nope", Attempt(id="x"))
