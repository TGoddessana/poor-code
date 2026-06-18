"""GlobalValidator helpers: changeset aggregation + the observe prompt preserving every
task's diff. The verdict/routing behaviour lives in test_global_validator_observe_judge.py."""
from pathlib import Path

from poor_code.domain.harness.nodes.global_validator import GlobalValidator, build_changeset
from poor_code.domain.session.models import (
    Attempt, AttemptStatus, ChangeRecord, Cursor, EditScope, Phase, Plan, Requirement,
    SessionState, Task, TaskStatus)


def _done_task(tid, fname, diff):
    att = Attempt(id=f"{tid}-a1", patch=ChangeRecord(files=(fname,), diff=diff),
                  status=AttemptStatus.DONE)
    return Task(id=tid, title=tid, purpose="p", edit_scope=EditScope(editable=(fname,)),
                how_to_validate="true", status=TaskStatus.DONE, attempts=(att,))


def _state(tasks):
    return SessionState(
        plan=Plan(tasks=tasks),
        requirement=Requirement(summary="do X", acceptance=("X works",)),
        cursor=Cursor(phase=Phase.FINALIZING, current_node="global_validator"))


def test_build_changeset_aggregates_done_attempt_diffs():
    st = _state((_done_task("t1", "a.txt", "diff-t1"), _done_task("t2", "b.txt", "diff-t2")))
    cs = build_changeset(st)
    assert cs.per_task == (("t1", "diff-t1"), ("t2", "diff-t2"))
    assert "diff-t1" in cs.aggregate_diff and "diff-t2" in cs.aggregate_diff


def test_observe_prompt_keeps_every_task_diff():
    # Per-task diffs are clamped individually so a later task is never wholly dropped by a
    # single aggregate cut — pin the last task's marker survives even after a huge first diff.
    st = _state((_done_task("t1", "a.txt", "A" * 5000),
                 _done_task("t2", "b.txt", "ZLAST-TASK-MARKER")))
    prompt = GlobalValidator(llm=None, cwd=Path("."))._observe_prompt(st)
    assert "ZLAST-TASK-MARKER" in prompt
    assert "t1" in prompt and "t2" in prompt
