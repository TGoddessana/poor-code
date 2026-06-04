import asyncio
import json
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.validator import Validator, MAX_ADVERSARIAL_ROUNDS
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
    Attempt, ChangeRecord, VerdictKind, Layer)
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class _JudgeLLM:
    def __init__(self, verdict, hint="h"):
        self._args = json.dumps({"verdict": verdict, "hint": hint})
    async def stream(self, messages, tools, response_format=None):
        yield ToolCallStarted(call_id="j1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="j1", json_delta=self._args)
        yield ToolCallEnded(call_id="j1")
        yield FinishedReason(reason="tool_calls")


def _state(rounds=0):
    att = Attempt(id="t1-a1", patch=ChangeRecord(files=("a.txt",), diff="d"),
                  adversarial_rounds=rounds)
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("a.txt",)),
                              how_to_validate="pytest", status=TaskStatus.ACTIVE,
                              attempts=(att,)),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="validator",
                      task_id="t1", attempt_id="t1-a1"))


class _CapturingJudgeLLM(_JudgeLLM):
    def __init__(self, verdict="advance"):
        super().__init__(verdict)
        self.seen = None
    async def stream(self, messages, tools, response_format=None):
        self.seen = messages
        async for ev in super().stream(messages, tools, response_format):
            yield ev


@pytest.mark.asyncio
async def test_validator_prompt_carries_scope_for_semantic_judgment():
    # Scope appropriateness moved from eng_gate's mechanical allowlist to the validator.
    # So the reviewer must SEE the task's intended editable scope and be told to judge
    # whether the patched files fit — a test sibling is fine, an unrelated module is not.
    llm = _CapturingJudgeLLM()
    await Validator(llm).run(NodeContext(state=_state(), cancel=asyncio.Event()))
    user = llm.seen[-1]["content"]
    system = llm.seen[0]["content"].lower()
    assert "a.txt" in user        # the declared editable scope reaches the reviewer
    assert "scope" in system      # the reviewer is instructed to judge scope fit


@pytest.mark.asyncio
async def test_validator_advance():
    res = await Validator(_JudgeLLM("advance")).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_validator_repair_impl():
    res = await Validator(_JudgeLLM("repair_impl", hint="missing edge case")).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.IMPLEMENTATION
    assert res.verdict.hint == "missing edge case"


@pytest.mark.asyncio
async def test_validator_repair_plan():
    res = await Validator(_JudgeLLM("repair_plan", hint="validation too weak")).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_validator_forces_advance_at_cap_without_calling_llm():
    class _Boom:
        async def stream(self, messages, tools, response_format=None):
            raise AssertionError("LLM must not be called at the cap")
            yield  # pragma: no cover
    res = await Validator(_Boom()).run(
        NodeContext(state=_state(rounds=MAX_ADVERSARIAL_ROUNDS), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ADVANCE
