from pathlib import Path
import uuid

from poor_code.domain.session.models import (
    ChangeSet, Policy, Report, ReportOutcome, SessionState, TaskReport, TaskStatus,
)
from poor_code.domain.session.store import SessionStore


def test_policy_and_report_roundtrip(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = uuid.uuid4().hex
    report = Report(
        outcome=ReportOutcome.ABANDONED,
        tasks=(TaskReport(task_id="t1", title="A", status=TaskStatus.DONE, attempts=1),),
        global_validation_passed=False,
        changeset=ChangeSet(aggregate_diff="diff", per_task=(("t1", "diff"),)),
        summary="0/1 done; ABANDONED")
    st = SessionState(policy=Policy.FULL_AUTO).with_report(report)

    store.write_session_state(sid, st)
    back = store.read_session_state(sid)

    assert back.policy is Policy.FULL_AUTO
    assert back.report == report


def test_missing_policy_and_report_default(tmp_path: Path):
    # A state written without policy/report (legacy) reads back with defaults.
    store = SessionStore(tmp_path)
    sid = uuid.uuid4().hex
    store.write_session_state(sid, SessionState())
    back = store.read_session_state(sid)
    assert back.policy is Policy.SUPERVISED
    assert back.report is None
