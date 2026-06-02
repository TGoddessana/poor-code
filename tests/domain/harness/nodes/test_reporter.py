import asyncio
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.reporter import (
    Reporter, build_report, report_from_dict, report_to_dict,
)
from poor_code.domain.session.models import (
    Attempt, EditScope, Plan, Report, ReportOutcome, SessionState, Task, TaskStatus,
)


def _state_two_tasks(*, second_done: bool) -> SessionState:
    t1 = Task(id="t1", title="A", purpose="p", edit_scope=EditScope(editable=("a.py",)),
              how_to_validate="true", status=TaskStatus.DONE,
              attempts=(Attempt(id="t1-a1"),))
    t2 = Task(id="t2", title="B", purpose="p", edit_scope=EditScope(editable=("b.py",)),
              how_to_validate="true",
              status=TaskStatus.DONE if second_done else TaskStatus.ABANDONED,
              attempts=(Attempt(id="t2-a1"), Attempt(id="t2-a2")))
    return SessionState(plan=Plan(tasks=(t1, t2)))


def test_build_report_succeeded():
    r = build_report(_state_two_tasks(second_done=True), ReportOutcome.SUCCEEDED)
    assert r.outcome is ReportOutcome.SUCCEEDED
    assert r.global_validation_passed is True
    assert len(r.tasks) == 2
    assert r.tasks[1].attempts == 2
    assert "2/2 tasks done" in r.summary


def test_build_report_abandoned():
    r = build_report(_state_two_tasks(second_done=False), ReportOutcome.ABANDONED)
    assert r.outcome is ReportOutcome.ABANDONED
    assert r.global_validation_passed is False
    assert "1/2 tasks done" in r.summary
    assert "ABANDONED" in r.summary


@pytest.mark.asyncio
async def test_reporter_node_emits_succeeded_report_and_is_terminal():
    from poor_code.domain.harness.route import route
    state = _state_two_tasks(second_done=True)
    result = await Reporter().run(NodeContext(state=state, cancel=asyncio.Event()))
    assert isinstance(result.output, Report)
    assert result.output.outcome is ReportOutcome.SUCCEEDED
    # terminal: no FORWARD edge from reporter, no verdict/branch → route returns None
    assert route("reporter", result, state) is None


def test_report_dict_roundtrip():
    r = build_report(_state_two_tasks(second_done=True), ReportOutcome.SUCCEEDED)
    assert report_from_dict(report_to_dict(r)) == r
