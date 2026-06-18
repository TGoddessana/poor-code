"""GlobalValidator v2 — the whole-build observation-grounded finishing validator.

Mirrors the per-task VerifierNode but at BUILD scope: it drives the integrated system
end-to-end against the full acceptance criteria, hunts for CROSS-TASK regressions, then
emits a verdict. Disposition is DEFAULT-ADVANCE (every task already passed its own
verification) and, critically, at the fixup cap it does BEST-EFFORT ADVANCE rather than
escalating to a 'user' node that does not exist headless (the park→false-abandon bug)."""
import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.global_validator import (
    GlobalValidator, MAX_FIXUPS, MAX_SCOPED_FIXUPS, observe_tools)
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Attempt, AttemptStatus, ChangeRecord, Cursor, Layer,
    Phase, Plan, Requirement, SessionState, Task, TaskReopened, TaskStatus, Transition,
    TriggerKind, VerdictKind)
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)

_TOOL = "assess_build"


class _GVLLM:
    """Two-phase fake: observe loop (bash/read/...) observes nothing and stops; judge
    phase (tool 'assess_build') emits the scripted whole-build verdict."""
    def __init__(self, verdict, hint="observed a cross-task regression", culprit="",
                 checks=None):
        payload = {"verdict": verdict, "hint": hint, "culprit_task_id": culprit}
        if checks is not None:
            payload["checks"] = checks
        self._args = json.dumps(payload)
        self.seen = None

    async def stream(self, messages, tools, response_format=None):
        if tools[0]["function"]["name"] == _TOOL:
            self.seen = messages
            yield ToolCallStarted(call_id="j1", name=_TOOL)
            yield ToolCallInputDelta(call_id="j1", json_delta=self._args)
            yield ToolCallEnded(call_id="j1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield TextDelta(text="observed enough")
            yield FinishedReason(reason="stop")


def _done_task(tid, fname):
    att = Attempt(id=f"{tid}-a1", patch=ChangeRecord(files=(fname,), diff=f"diff-{tid}"),
                  status=AttemptStatus.DONE)
    return Task(id=tid, title=tid, purpose="p", edit_scope=__import__(
        "poor_code.domain.session.models", fromlist=["EditScope"]).EditScope(
            editable=(fname,)),
        how_to_validate="true", status=TaskStatus.DONE, attempts=(att,))


def _state(history=()):
    return SessionState(
        plan=Plan(tasks=(_done_task("t1", "a.txt"), _done_task("t2", "b.txt"))),
        history=tuple(history),
        acceptance=AcceptanceSpec(checks=(AcceptanceCheck(criterion="build works"),)),
        requirement=Requirement(summary="do X", acceptance=("X works",)),
        cursor=Cursor(phase=Phase.FINALIZING, current_node="global_validator"))


def _gv_transition(to_node):
    return Transition(from_node="global_validator", to_node=to_node,
                      trigger=TriggerKind.GATE, reason="x", ts_iso="t")


def _node(llm, cwd="."):
    return GlobalValidator(llm, cwd=cwd, tools=observe_tools())


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_advance_passes_to_reporter():
    res = await _node(_GVLLM("advance")).run(_ctx(_state()))
    assert res.branch == "pass"


@pytest.mark.asyncio
async def test_repair_impl_with_culprit_does_scoped_reopen():
    res = await _node(_GVLLM("repair_impl", culprit="t2")).run(_ctx(_state()))
    assert res.verdict is not None and res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.IMPLEMENTATION
    assert isinstance(res.output, TaskReopened) and res.output.task_id == "t2"
    # reopening flips ONLY the culprit DONE -> PENDING so task_selector re-runs it
    new_state = res.output.apply_to(_state())
    assert next(t for t in new_state.plan.tasks if t.id == "t2").status is TaskStatus.PENDING
    assert next(t for t in new_state.plan.tasks if t.id == "t1").status is TaskStatus.DONE


@pytest.mark.asyncio
async def test_repair_plan_bubbles_to_plan_layer():
    res = await _node(_GVLLM("repair_plan", hint="decomposition wrong")).run(_ctx(_state()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_repair_impl_without_culprit_falls_back_to_replan():
    res = await _node(_GVLLM("repair_impl", culprit="")).run(_ctx(_state()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_unknown_culprit_id_falls_back_to_replan():
    res = await _node(_GVLLM("repair_impl", culprit="t99")).run(_ctx(_state()))
    assert res.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_scoped_budget_exhausted_falls_back_to_replan():
    history = [_gv_transition("implement_loop") for _ in range(MAX_SCOPED_FIXUPS)]
    res = await _node(_GVLLM("repair_impl", culprit="t2")).run(_ctx(_state(history)))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_best_effort_advance_when_all_budgets_exhausted():
    # THE finish-line false-abandon fix: when both scoped and full-replan budgets are spent,
    # global_validator must NOT escalate (-> 'user' node, which is unregistered headless and
    # parks/abandons a correct-on-disk build). It advances best-effort to the reporter.
    history = ([_gv_transition("implement_loop") for _ in range(MAX_SCOPED_FIXUPS)]
               + [_gv_transition("planner") for _ in range(MAX_FIXUPS)])
    res = await _node(_GVLLM("repair_impl", culprit="t2")).run(_ctx(_state(history)))
    assert res.branch == "pass"
    assert res.verdict is None or res.verdict.kind is not VerdictKind.ESCALATE


@pytest.mark.asyncio
async def test_observe_prompt_carries_criteria():
    llm = _GVLLM("advance")
    await _node(llm).run(_ctx(_state()))
    blob = "\n".join(str(m.get("content", "")) for m in llm.seen)
    assert "build works" in blob   # the acceptance criterion reached the validator's judge


@pytest.mark.asyncio
async def test_observe_runs_tools_in_node_cwd_and_no_leak(tmp_path):
    from pydantic import BaseModel
    from poor_code.domain.tool.registry import ToolRegistry

    seen = {}

    class _BashArgs(BaseModel):
        command: str = ""

    class _BashStub:
        id = "bash"; description = "x"; params = _BashArgs
        async def execute(self, args, ctx):
            seen["cwd"] = ctx.cwd
            class R: output = "ran"
            return R()

    class _LLM:
        def __init__(self): self.round = 0
        async def stream(self, messages, tools, response_format=None):
            self.round += 1
            if self.round == 1:
                yield TextDelta(text="secret reasoning")
                yield ToolCallStarted(call_id="b1", name="bash")
                yield ToolCallInputDelta(call_id="b1", json_delta='{"command":"ls"}')
                yield ToolCallEnded(call_id="b1")
                yield FinishedReason(reason="tool_calls")
            else:
                yield FinishedReason(reason="stop")

    class _Sink:
        def __init__(self): self.text = []
        def node_thinking_delta(self, name, t): self.text.append(t)
        def __getattr__(self, _n): return lambda *a, **k: None

    node = GlobalValidator(_LLM(), cwd=tmp_path, tools=ToolRegistry([_BashStub()]))
    sink = _Sink()
    state = _state()
    ctx = NodeContext(state=state, cancel=asyncio.Event(), sink=sink)
    history = await node._observe(ctx)
    assert seen["cwd"] == tmp_path
    assert sink.text == []
    assert any(m["role"] == "tool" for m in history)
