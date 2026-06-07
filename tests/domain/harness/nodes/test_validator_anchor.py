from poor_code.domain.harness.nodes.validator import Validator
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, AcceptanceSpec, AcceptanceCheck,
)


def _state():
    task = Task(id="t1", title="fib", purpose="",
                edit_scope=EditScope(editable=("server.py",)))
    return SessionState(
        plan=Plan(tasks=(task,), plan_md="## t1: server.py — fib handler"),
        acceptance=AcceptanceSpec(checks=(AcceptanceCheck(criterion="n=10 -> 55",
                                                          command="curl ... | grep -qx 55"),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="validator", task_id="t1"))


def test_validator_messages_include_acceptance_and_ledger():
    msgs = Validator(llm=None).build_messages(_state())
    blob = "\n".join(m["content"] for m in msgs)
    assert "n=10 -> 55" in blob           # full acceptance spec present
    assert "## t1" in blob                # task md section present
    assert "completed work" in blob.lower() or "✓" in blob  # ledger present


def test_validator_messages_editable_scope_still_present():
    msgs = Validator(llm=None).build_messages(_state())
    blob = "\n".join(m["content"] for m in msgs)
    assert "server.py" in blob


def test_task_section_fallback_when_no_marker():
    from poor_code.domain.harness.nodes.validator import _task_section
    from poor_code.domain.session.models import Plan
    plan = Plan(tasks=(), plan_md="## t2: something else")
    # no "## t1" in md — should return full md (not just task_id)
    result = _task_section(plan, "t1")
    assert result == "## t2: something else"


def test_task_section_extracts_correct_slice():
    from poor_code.domain.harness.nodes.validator import _task_section
    from poor_code.domain.session.models import Plan
    md = "## t1: first\ncontent1\n## t2: second\ncontent2"
    plan = Plan(tasks=(), plan_md=md)
    assert _task_section(plan, "t1") == "## t1: first\ncontent1"
    assert _task_section(plan, "t2") == "## t2: second\ncontent2"
