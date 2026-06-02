from poor_code.domain.session.models import (
    ChangeSet, Report, ReportOutcome, SessionState, TaskReport, TaskStatus,
)


def test_report_objects_construct():
    tr = TaskReport(task_id="t1", title="Add login", status=TaskStatus.DONE, attempts=2)
    r = Report(outcome=ReportOutcome.SUCCEEDED, tasks=(tr,),
               global_validation_passed=True, changeset=ChangeSet(), summary="1/1 done")
    assert r.outcome is ReportOutcome.SUCCEEDED
    assert r.tasks[0].attempts == 2


def test_with_report_sets_field_immutably():
    st = SessionState()
    assert st.report is None
    r = Report(outcome=ReportOutcome.ABANDONED)
    st2 = st.with_report(r)
    assert st2.report is r
    assert st.report is None  # original untouched
