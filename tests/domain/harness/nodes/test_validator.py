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


# ── A1: Literal verdict, drop silent default ──────────────────────────────────

def test_typo_verdict_is_rejected_not_silently_advanced():
    v = Validator(llm=None)  # parse() only; no LLM needed
    with pytest.raises(Exception):  # StructuredOutputError
        v.parse('{"verdict": "REPAIR_IMPL", "hint": "x"}')


def test_missing_verdict_is_rejected():
    v = Validator(llm=None)
    with pytest.raises(Exception):  # StructuredOutputError
        v.parse('{"hint": "x"}')


# ── A2: synthesize repair hint from OBSERVED when model omits it ──────────────

def test_empty_repair_hint_is_synthesized_from_observed():
    v = Validator(llm=None)
    v._observed = [("pytest passes", False, "E   AssertionError: 1 != 2")]
    verdict = v.parse('{"verdict": "repair_impl", "hint": ""}')
    assert verdict.hint  # must not be empty
    assert "AssertionError" in verdict.hint  # carries the observed failure tail


def test_empty_repair_plan_hint_is_also_synthesized():
    v = Validator(llm=None)
    v._observed = [("pytest passes", False, "E   AssertionError: boom")]
    verdict = v.parse('{"verdict": "repair_plan", "hint": ""}')
    assert "AssertionError" in verdict.hint  # repair_plan branch synthesizes too


def test_synth_hint_omits_trailing_colon_when_tail_empty():
    v = Validator(llm=None)
    v._observed = [("build succeeds", False, "")]
    verdict = v.parse('{"verdict": "repair_impl", "hint": ""}')
    assert "build succeeds" in verdict.hint
    assert "build succeeds:" not in verdict.hint  # no dangling colon


# ── B3: tail-biased clamp keeps failure tail ──────────────────────────────────

def test_observed_clamp_keeps_failure_tail():
    from poor_code.domain.harness.tool_output import clamp_tool_output
    big = "starting tests\n" + "ok\n" * 5000 + "E   AssertionError: tail-error"
    assert "tail-error" in clamp_tool_output(big, head=300, tail=1200)
