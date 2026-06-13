import asyncio
import json
import pytest

from poor_code.domain.harness.node import NodeContext, StructuredOutputError, validate_output
from poor_code.domain.harness.nodes.global_validator import (
    GlobalValidator, build_changeset, MAX_FIXUPS, _AnalyzeOut)
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, SessionState, Plan, Task, EditScope, Cursor, Phase,
    TaskStatus, Attempt, AttemptStatus, ChangeRecord, Transition, TriggerKind, VerdictKind,
    Layer)
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class _AnalyzeLLM:
    def __init__(self, hint="task t2 broke t1"):
        self._args = json.dumps({"hint": hint})
    async def stream(self, messages, tools, response_format=None):
        yield ToolCallStarted(call_id="a1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="a1", json_delta=self._args)
        yield ToolCallEnded(call_id="a1")
        yield FinishedReason(reason="tool_calls")


class _NoLLM:
    async def stream(self, messages, tools, response_format=None):
        raise AssertionError("LLM must not be called when all validations pass")
        yield  # pragma: no cover


def _done_task(tid, validate, fname):
    att = Attempt(id=f"{tid}-a1", patch=ChangeRecord(files=(fname,), diff=f"diff-{tid}"),
                  status=AttemptStatus.DONE)
    return Task(id=tid, title=tid, purpose="p", edit_scope=EditScope(editable=(fname,)),
                how_to_validate=validate, status=TaskStatus.DONE, attempts=(att,))


def _state(tasks, history=(), acceptance=None):
    return SessionState(
        plan=Plan(tasks=tasks), history=history, acceptance=acceptance,
        cursor=Cursor(phase=Phase.FINALIZING, current_node="global_validator"))


def _failing_acceptance():
    return AcceptanceSpec(checks=(AcceptanceCheck(criterion="must pass", command="false"),))


def test_build_changeset_aggregates_done_attempt_diffs():
    st = _state((_done_task("t1", "true", "a.txt"), _done_task("t2", "true", "b.txt")))
    cs = build_changeset(st)
    assert cs.per_task == (("t1", "diff-t1"), ("t2", "diff-t2"))
    assert "diff-t1" in cs.aggregate_diff and "diff-t2" in cs.aggregate_diff


@pytest.mark.asyncio
async def test_global_validator_pass_when_all_validations_succeed(tmp_path):
    st = _state((_done_task("t1", "true", "a.txt"),))
    res = await GlobalValidator(_NoLLM(), cwd=tmp_path).run(
        NodeContext(state=st, cancel=asyncio.Event()))
    assert res.branch == "pass"


@pytest.mark.asyncio
async def test_global_validator_passes_through_in_v2_even_with_failing_acceptance(tmp_path):
    # Verification v2: global_validator no longer RE-RUNS model-authored bash acceptance
    # checks (that was the last bash floor that false-abandoned correct builds). The
    # per-task Verifier owns verification by observation, so the finishing gate just
    # passes — even a `false` acceptance command is not run, and the LLM is not consulted.
    st = _state((_done_task("t1", "true", "a.txt"),), acceptance=_failing_acceptance())
    res = await GlobalValidator(_NoLLM(), cwd=tmp_path).run(
        NodeContext(state=st, cancel=asyncio.Event()))
    assert res.branch == "pass"


def test_global_validator_requires_nonempty_hint():
    with pytest.raises(StructuredOutputError):
        validate_output(_AnalyzeOut, '{"culprit_task_id": "t1"}', node="global_validator")


# ── B4: per-task diffs so no later task is dropped by an aggregate cut ────────

def test_build_messages_keeps_every_task_diff():
    from pathlib import Path
    from poor_code.domain.session.models import ChangeSet
    gv = GlobalValidator(llm=None, cwd=Path("."))
    gv._failures = [("acceptance:x", 1, "boom")]
    gv._changeset = ChangeSet(
        aggregate_diff="huge",
        per_task=(("t1", "A" * 5000), ("t2", "ZLAST-TASK-MARKER")))
    msg = gv.build_messages(state=None)[-1]["content"]
    assert "ZLAST-TASK-MARKER" in msg   # last task survives (not dropped by a 4000-char aggregate cut)
    assert "t1" in msg and "t2" in msg
