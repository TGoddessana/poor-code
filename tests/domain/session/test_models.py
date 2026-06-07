from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.session.models import (
    Plan,
    WorkItemPolicies,
    Session,
    SessionState,
    SessionStatus,
    WorkItem,
    WorkItemState,
    WorkItemStatus,
)


def test_session_is_frozen_and_round_trips_via_replace():
    s = Session(
        session_id="abc",
        cwd=Path("/tmp/x"),
        created_at=datetime(2026, 5, 26, tzinfo=UTC),
    )
    s2 = replace(s, parent_session_id="def")
    assert s.parent_session_id is None
    assert s2.parent_session_id == "def"
    assert s != s2


def test_session_state_defaults_to_ready_no_task():
    st = SessionState()
    assert st.status is SessionStatus.READY
    assert st.active_task_id is None


def test_task_state_defaults_to_pending_with_locked_policies():
    ts = WorkItemState()
    assert ts.status is WorkItemStatus.PENDING
    assert ts.policies.implementation_locked is True


def test_task_status_terminal_values_exist():
    assert WorkItemStatus.DONE.value == "done"
    assert WorkItemStatus.ABORTED.value == "aborted"


def test_policies_is_value_object():
    p1 = WorkItemPolicies()
    p2 = WorkItemPolicies()
    assert p1 == p2
    assert p1 is not p2


def test_plan_carries_markdown_body():
    p = Plan(plan_md="## t1: do X\n## t2: do Y")
    assert p.plan_md.startswith("## t1")
    assert p.tasks == ()  # default still empty


def test_attempt_carries_check_results():
    from poor_code.domain.session.models import Attempt
    a = Attempt(id="t1.a1", check_results=(("n=10 -> 55", True), ("neg", False)))
    assert dict(a.check_results)["n=10 -> 55"] is True
