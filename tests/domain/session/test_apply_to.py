"""각 출력 타입의 apply_to 가 기존 Driver._apply 와 동일하게 state 를 갱신하는지."""
from dataclasses import replace
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Plan, Task, EditScope, TaskStatus, AttemptStatus,
    Request, RequestKind, CodeContext, CodeRef, Requirement, AcceptanceSpec,
    AcceptanceCheck, SelectedTask, TaskContext, Attempt, ChangeRecord,
    ValidationResult, FeedbackEntry, TaskCompleted, Report, ReportOutcome, EnvReport,
)


def _base():
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p",
                            edit_scope=EditScope(editable=("a.txt",)),
                            how_to_validate="test -f a.txt", status=TaskStatus.ACTIVE),))
    return SessionState(plan=plan,
                        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="x", task_id="t1"))


def test_request_apply_to():
    s = Request(raw_text="r", kind=RequestKind.ENGINEERING).apply_to(SessionState())
    assert s.request.kind is RequestKind.ENGINEERING


def test_codecontext_apply_to_clears_repair_hint():
    s0 = SessionState(repair_hint="old")
    s = CodeContext(candidates=(CodeRef(file="a.py", symbol="x"),)).apply_to(s0)
    assert s.understanding.candidates[0].symbol == "x"
    assert s.repair_hint is None


def test_requirement_apply_to():
    s = Requirement(summary="done").apply_to(SessionState())
    assert s.requirement.summary == "done"


def test_plan_apply_to():
    p = Plan(tasks=(Task(id="t1", title="A", purpose="p"),))
    assert p.apply_to(SessionState()).plan is p


def test_acceptance_apply_to():
    spec = AcceptanceSpec(checks=(AcceptanceCheck(criterion="c", command="true"),))
    assert spec.apply_to(SessionState()).acceptance is spec


def test_selected_task_apply_to_uses_own_task_id():
    s = SelectedTask(task_id="t1").apply_to(_base())
    assert s.cursor.task_id == "t1"
    assert [t for t in s.plan.tasks if t.id == "t1"][0].status is TaskStatus.ACTIVE


def test_task_context_apply_to_uses_cursor_task_id():
    s = TaskContext(refs=(CodeRef(file="a.txt"),)).apply_to(_base())
    assert s.plan.tasks[0].context.refs[0].file == "a.txt"


def test_attempt_apply_to_upserts_and_clears_hint():
    s = Attempt(id="t1-a1", patch=ChangeRecord(files=("a.txt",))).apply_to(
        _base().with_active_task("t1").with_repair_hint("h"))
    assert s.plan.tasks[0].attempts[0].id == "t1-a1"
    assert s.repair_hint is None


def test_validation_result_apply_to_uses_cursor():
    base = _base().with_active_task("t1").append_attempt("t1", Attempt(id="a1"))
    base = replace(base, cursor=replace(base.cursor, task_id="t1", attempt_id="a1"))
    s = ValidationResult(command="true", exit_code=0, passed=True).apply_to(base)
    assert s.plan.tasks[0].attempts[0].run_result.passed is True


def test_feedback_entry_apply_to():
    s = FeedbackEntry(failure_type="x", symptom="y", prevention_hint="z").apply_to(SessionState())
    assert s.feedback.entries[0].failure_type == "x"


def test_task_completed_apply_to():
    s0 = _base().with_active_task("t1").append_attempt("t1", Attempt(id="a1"))
    s = TaskCompleted(task_id="t1", attempt_id="a1").apply_to(s0)
    assert s.plan.tasks[0].status is TaskStatus.DONE
    assert s.plan.tasks[0].attempts[0].status is AttemptStatus.DONE


def test_report_apply_to():
    r = Report(outcome=ReportOutcome.SUCCEEDED, summary="ok")
    assert r.apply_to(SessionState()).report is r


def test_env_report_apply_to():
    er = EnvReport()
    assert er.apply_to(SessionState()).env_report is er
