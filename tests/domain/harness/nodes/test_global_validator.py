import asyncio
import json
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.global_validator import (
    GlobalValidator, build_changeset, MAX_FIXUPS)
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
    Attempt, AttemptStatus, ChangeRecord, Transition, TriggerKind, VerdictKind, Layer)
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


def _state(tasks, history=()):
    return SessionState(
        plan=Plan(tasks=tasks), history=history,
        cursor=Cursor(phase=Phase.FINALIZING, current_node="global_validator"))


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
async def test_global_validator_repairs_plan_on_regression(tmp_path):
    st = _state((_done_task("t1", "false", "a.txt"),))  # `false` → exit 1
    res = await GlobalValidator(_AnalyzeLLM("t1 regressed"), cwd=tmp_path).run(
        NodeContext(state=st, cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN
    assert res.verdict.hint == "t1 regressed"


@pytest.mark.asyncio
async def test_global_validator_escalates_at_fixup_cap(tmp_path):
    fixups = tuple(
        Transition(from_node="global_validator", to_node="planner",
                   trigger=TriggerKind.GATE, reason="fixup", ts_iso="t")
        for _ in range(MAX_FIXUPS))
    st = _state((_done_task("t1", "false", "a.txt"),), history=fixups)
    res = await GlobalValidator(_NoLLM(), cwd=tmp_path).run(
        NodeContext(state=st, cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ESCALATE
