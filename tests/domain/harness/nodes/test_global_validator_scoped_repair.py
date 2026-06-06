"""FM3-deep: scoped (hierarchical) repair. A regression that the analyst pins to a
single culprit task must reopen ONLY that task and re-enter the implement loop, not
restart the entire plan→reviewer→provisioner→all-tasks cycle (which burned the 1800s
wall on a one-line fix in fix-git). Full re-plan stays the fallback when no culprit is
identified or the scoped budget is spent."""
import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.global_validator import (
    GlobalValidator, MAX_SCOPED_FIXUPS,
)
from poor_code.domain.session.models import (
    Layer, Plan, SessionState, Task, TaskStatus, Transition, TriggerKind, VerdictKind,
)


def _llm(payload):
    class _LLM:
        async def stream(self, messages, tools, response_format=None):
            from poor_code.provider.events import (
                FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)
            yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
            yield ToolCallInputDelta(call_id="c1", json_delta=json.dumps(payload))
            yield ToolCallEnded(call_id="c1")
            yield FinishedReason(reason="tool_calls")
    return _LLM()


def _state(history=()):
    # two DONE tasks; t2's validation fails (regression). t1 passes.
    t1 = Task(id="t1", title="a", purpose="p", how_to_validate="true",
              status=TaskStatus.DONE)
    t2 = Task(id="t2", title="b", purpose="p", how_to_validate="false",
              status=TaskStatus.DONE)
    return SessionState(plan=Plan(tasks=(t1, t2)), history=tuple(history))


def _gv_transition(to_node):
    return Transition(from_node="global_validator", to_node=to_node,
                      trigger=TriggerKind.GATE, reason="x", ts_iso="t")


@pytest.mark.asyncio
async def test_scoped_repair_reopens_culprit_and_repairs_implementation(tmp_path):
    gv = GlobalValidator(_llm({"hint": "t2 broke it", "culprit_task_id": "t2"}),
                         cwd=tmp_path)
    res = await gv.run(NodeContext(_state(), cancel=asyncio.Event()))
    assert res.verdict is not None and res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.IMPLEMENTATION
    # the output reopens the culprit (DONE -> PENDING) so task_selector re-runs it
    new_state = res.output.apply_to(_state())
    t2 = next(t for t in new_state.plan.tasks if t.id == "t2")
    assert t2.status is TaskStatus.PENDING
    t1 = next(t for t in new_state.plan.tasks if t.id == "t1")
    assert t1.status is TaskStatus.DONE  # untouched


@pytest.mark.asyncio
async def test_falls_back_to_replan_when_no_culprit_identified(tmp_path):
    gv = GlobalValidator(_llm({"hint": "something broke", "culprit_task_id": ""}),
                         cwd=tmp_path)
    res = await gv.run(NodeContext(_state(), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_falls_back_to_replan_when_scoped_budget_exhausted(tmp_path):
    history = [_gv_transition("implement_loop") for _ in range(MAX_SCOPED_FIXUPS)]
    gv = GlobalValidator(_llm({"hint": "h", "culprit_task_id": "t2"}), cwd=tmp_path)
    res = await gv.run(NodeContext(_state(history), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_ignores_unknown_culprit_id(tmp_path):
    gv = GlobalValidator(_llm({"hint": "h", "culprit_task_id": "t99"}), cwd=tmp_path)
    res = await gv.run(NodeContext(_state(), cancel=asyncio.Event()))
    assert res.verdict.layer is Layer.PLAN  # unknown id -> not a scoped repair
