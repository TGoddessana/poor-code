"""VerifierNode — the observation-grounded adversarial verifier that replaces the
bash-check chain. It runs an observe tool loop (here the fake LLM observes nothing and
stops), then emits a verdict that maps to advance(done) / repair_impl / repair_plan, with
a LOOSENED authority: at the attempt cap it accepts best-effort rather than abandoning."""
import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext, StructuredOutputError
from poor_code.domain.harness.nodes.execution import MAX_ATTEMPTS
from poor_code.domain.harness.nodes.verifier import VerifierNode
from poor_code.domain.harness.subgraphs.implement_loop import _verifier_tools
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Attempt, ChangeRecord, Cursor, Layer, Phase,
    Plan, Requirement, SessionState, Task, TaskCompleted, TaskStatus, VerdictKind,
)
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class _VerifierLLM:
    """Two-phase fake: in the observe loop (tools = bash/read/...) it observes nothing
    and stops; in the judge phase (tool 'judge') it emits the scripted verdict."""
    def __init__(self, verdict, hint="because observed"):
        self._args = json.dumps({"verdict": verdict, "hint": hint})
        self.seen = None

    async def stream(self, messages, tools, response_format=None):
        name = tools[0]["function"]["name"]
        if name == "judge":
            self.seen = messages
            yield ToolCallStarted(call_id="j1", name="judge")
            yield ToolCallInputDelta(call_id="j1", json_delta=self._args)
            yield ToolCallEnded(call_id="j1")
            yield FinishedReason(reason="tool_calls")
        else:  # observe phase — look at nothing, stop immediately
            yield TextDelta(text="observed enough")
            yield FinishedReason(reason="stop")


def _state(*, n_attempts=1):
    attempts = tuple(
        Attempt(id=f"t1-a{i+1}", patch=ChangeRecord(files=("a.py",), diff="d"))
        for i in range(n_attempts))
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="A", purpose="p",
                              status=TaskStatus.ACTIVE, attempts=attempts),)),
        acceptance=AcceptanceSpec(checks=(
            AcceptanceCheck(criterion="empty input shows an error"),)),
        requirement=Requirement(summary="do X", acceptance=("X works",)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="verifier",
                      task_id="t1", attempt_id=attempts[-1].id))


def _node(llm):
    return VerifierNode(llm, cwd=".", tools=_verifier_tools())


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


def test_name_is_verifier():
    assert _node(_VerifierLLM("advance")).name == "verifier"


@pytest.mark.asyncio
async def test_advance_marks_task_done():
    r = await _node(_VerifierLLM("advance")).run(_ctx(_state()))
    assert r.branch == "done"
    assert isinstance(r.output, TaskCompleted) and r.output.task_id == "t1"


@pytest.mark.asyncio
async def test_repair_impl_below_cap():
    r = await _node(_VerifierLLM("repair_impl", hint="empty input crashed")).run(_ctx(_state()))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.IMPLEMENTATION
    assert "empty input crashed" in r.verdict.hint


@pytest.mark.asyncio
async def test_repair_plan_bubbles_to_plan_layer():
    r = await _node(_VerifierLLM("repair_plan", hint="wrong files")).run(_ctx(_state()))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_at_cap_accepts_best_effort_instead_of_abandoning():
    # Loosened authority: at the attempt cap a repair_impl verdict does NOT abandon —
    # it accepts best-effort and moves on (no rigid park/abandon).
    r = await _node(_VerifierLLM("repair_impl")).run(_ctx(_state(n_attempts=MAX_ATTEMPTS)))
    assert r.branch == "done"
    assert isinstance(r.output, TaskCompleted)


def test_parse_rejects_unknown_verdict():
    with pytest.raises(StructuredOutputError):
        _node(None).parse('{"verdict": "ADVANCE", "hint": "x"}')


@pytest.mark.asyncio
async def test_observe_prompt_carries_criteria():
    llm = _VerifierLLM("advance")
    await _node(llm).run(_ctx(_state()))
    # the judge phase sees the observation history, which began with the criteria prompt
    blob = "\n".join(str(m.get("content", "")) for m in llm.seen)
    assert "empty input shows an error" in blob   # the criterion reached the verifier
