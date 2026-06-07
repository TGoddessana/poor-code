from poor_code.domain.harness.ledger import render_build_ledger
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, TaskStatus, Attempt, AttemptStatus,
    AcceptanceSpec, AcceptanceCheck,
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


def test_task_section_exact_token_no_prefix_collision():
    from poor_code.domain.harness.ledger import task_section
    from poor_code.domain.session.models import Plan
    plan = Plan(plan_md="## t1: alpha\nbody1\n## t10: beta\nbody10")
    sec = task_section(plan, "t1")
    assert "alpha" in sec and "beta" not in sec     # t1 must NOT swallow t10
    assert task_section(plan, "t10").startswith("## t10")

def test_task_section_fallback():
    from poor_code.domain.harness.ledger import task_section
    from poor_code.domain.session.models import Plan
    assert task_section(Plan(plan_md="## tX: x"), "t9") == "## tX: x"
    assert task_section(None, "t1") == "t1"

def test_has_section_exact_token():
    from poor_code.domain.harness.ledger import has_section
    md = "## t1: a\n## t10: b"
    assert has_section(md, "t1") and has_section(md, "t10")
    assert not has_section("## t10: b", "t1")


def test_render_acceptance():
    from poor_code.domain.harness.ledger import render_acceptance
    from poor_code.domain.session.models import SessionState, AcceptanceSpec, AcceptanceCheck
    s = SessionState(acceptance=AcceptanceSpec(checks=(AcceptanceCheck("n=10->55","curl"),)))
    out = render_acceptance(s)
    assert "n=10->55" in out and "curl" in out
    assert render_acceptance(SessionState()).strip() == "(none)"
