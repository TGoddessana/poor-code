from poor_code.domain.harness.ledger import render_build_ledger
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, TaskStatus, Attempt, AttemptStatus,
)


def _state():
    done = Task(id="t1", title="fib handler", purpose="", status=TaskStatus.DONE,
                edit_scope=EditScope(editable=("server.py",)),
                attempts=(Attempt(id="t1.a1", status=AttemptStatus.DONE,
                                  check_results=(("n=10 -> 55", True),)),))
    todo = Task(id="t2", title="validation", purpose="",
                edit_scope=EditScope(editable=("server.py",)))
    return SessionState(plan=Plan(tasks=(done, todo)))


def test_ledger_lists_done_tasks_and_green_checks():
    text = render_build_ledger(_state())
    assert "t1" in text and "fib handler" in text
    assert "n=10 -> 55" in text          # green check recorded
    assert "t2" not in text or "pending" in text.lower()  # only completed work narrated


def test_ledger_empty_when_no_done_tasks():
    text = render_build_ledger(SessionState(plan=Plan(tasks=())))
    assert "(none" in text.lower() or text.strip() == "" or "no completed" in text.lower()
