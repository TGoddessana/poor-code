from poor_code.domain.harness.nodes.gates import PlanGate
from poor_code.domain.session.models import (
    EditScope, FileSlot, Plan, Step, StepKind, Task)


def _task(**kw):
    base = dict(id="t1", title="t", purpose="p",
                edit_scope=EditScope(editable=("x.py",)))
    base.update(kw)
    return Task(**base)


def _plan(task, file_plan=(FileSlot(path="x.py", responsibility="r"),)):
    return Plan(tasks=(task,), file_plan=file_plan,
                plan_md=f"## {task.id}: x.py — do x")


def test_rejects_placeholder_body():
    task = _task(steps=(Step(id="t1-s1", kind=StepKind.IMPL, file="x.py",
                             body="def f():\n    pass  # TODO implement"),))
    hint = PlanGate._invalid_hint(_plan(task))
    assert hint is not None and "t1-s1" in hint


def test_rejects_empty_impl_body():
    task = _task(steps=(Step(id="t1-s1", kind=StepKind.IMPL, file="x.py", body=""),))
    hint = PlanGate._invalid_hint(_plan(task))
    assert hint is not None and "t1-s1" in hint


def test_rejects_run_step_missing_expected():
    task = _task(steps=(Step(id="t1-s1", kind=StepKind.RUN, run="pytest", expected=""),))
    hint = PlanGate._invalid_hint(_plan(task))
    assert hint is not None and "t1-s1" in hint


def test_rejects_editable_absent_from_file_plan():
    task = _task(edit_scope=EditScope(editable=("y.py",)))   # y.py not in file_plan (x.py)
    hint = PlanGate._invalid_hint(_plan(task))
    assert hint is not None and ("y.py" in hint or "file_plan" in hint.lower())


def test_accepts_clean_thick_plan():
    task = _task(steps=(
        Step(id="t1-s1", kind=StepKind.TEST, file="tests/x.py", body="def test_f():\n    assert f()==1"),
        Step(id="t1-s2", kind=StepKind.RUN, run="pytest tests/x.py", expected="FAIL"),
        Step(id="t1-s3", kind=StepKind.IMPL, file="x.py", body="def f():\n    return 1"),
        Step(id="t1-s4", kind=StepKind.RUN, run="pytest tests/x.py", expected="1 passed"),
    ))
    assert PlanGate._invalid_hint(_plan(task)) is None


def test_no_steps_still_accepted():
    # Advisory backstop: a thin plan (no steps) must still flow (weak-model fallback).
    assert PlanGate._invalid_hint(_plan(_task(steps=()))) is None


def test_legit_code_with_todo_identifier_not_rejected():
    # A function named parse_todo is NOT a placeholder — it's real code.
    task = _task(steps=(Step(id="t1-s1", kind=StepKind.IMPL, file="x.py",
                             body="def parse_todo(line):\n    return line.startswith('TODO')"),))
    assert PlanGate._invalid_hint(_plan(task)) is None


def test_comment_todo_marker_is_rejected():
    # A # TODO: comment inside a body IS a placeholder and must be rejected.
    task = _task(steps=(Step(id="t1-s1", kind=StepKind.IMPL, file="x.py",
                             body="def f():\n    pass  # TODO: implement"),))
    hint = PlanGate._invalid_hint(_plan(task))
    assert hint is not None and "t1-s1" in hint
