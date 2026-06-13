"""CompletionJudge — the completion decision is now an LLM judge sitting ON TOP of
the objective floor. It may DEMOTE a passing task (checks pass but intent unmet) and
classify a failure (impl hole / mis-scoped plan / BROKEN check), but it may NEVER
PROMOTE a task past a failing binding check. The node keeps the wiring name
'completion_gate' so the graph topology is unchanged."""
import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext, StructuredOutputError
from poor_code.domain.harness.nodes.completion_judge import CompletionJudge
from poor_code.domain.harness.nodes.execution import MAX_ATTEMPTS
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Attempt, ChangeRecord, Cursor, Layer, Phase,
    Plan, Requirement, SessionState, Task, TaskCompleted, TaskStatus,
    ValidationResult, VerdictKind,
)


class _DecisionLLM:
    """Emits one forced decision tool call with the given verdict/reason."""
    def __init__(self, verdict, reason="because"):
        self._args = json.dumps({"verdict": verdict, "reason": reason})
        self.seen = None

    async def stream(self, messages, tools, response_format=None):
        from poor_code.provider.events import (
            FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)
        self.seen = messages
        yield ToolCallStarted(call_id="d1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="d1", json_delta=self._args)
        yield ToolCallEnded(call_id="d1")
        yield FinishedReason(reason="tool_calls")


def _state(*, passed, n_attempts=1, binding=True, how_to_validate=""):
    """A state parked at completion with a validation_runner result already recorded."""
    rr = ValidationResult(
        command="checks", exit_code=0 if passed else 1, passed=passed,
        output=("all green" if passed else "no acceptance progress: 0/1 green"),
        check_results=(("criterion-1", passed),))
    attempts = tuple(
        Attempt(id=f"t1-a{i+1}", patch=ChangeRecord(files=("a.py",), diff="d"),
                run_result=(rr if i == n_attempts - 1 else None))
        for i in range(n_attempts))
    accept = AcceptanceSpec(checks=(AcceptanceCheck(criterion="criterion-1",
                                                    command="true"),)) if binding else None
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="A", purpose="p",
                              how_to_validate=how_to_validate,
                              status=TaskStatus.ACTIVE, attempts=attempts),)),
        acceptance=accept,
        requirement=Requirement(summary="do X", acceptance=("X works",)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="completion_gate",
                      task_id="t1", attempt_id=attempts[-1].id))


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


def test_wiring_name_is_completion_gate():
    # The graph edges reference 'completion_gate'; the judge MUST keep that name so the
    # topology is unchanged when the deterministic gate is swapped for the LLM judge.
    assert CompletionJudge(_DecisionLLM("done")).name == "completion_gate"


@pytest.mark.asyncio
async def test_done_when_checks_pass_and_judge_agrees():
    r = await CompletionJudge(_DecisionLLM("done")).run(_ctx(_state(passed=True)))
    assert r.branch == "done"
    assert isinstance(r.output, TaskCompleted) and r.output.task_id == "t1"


@pytest.mark.asyncio
async def test_floor_veto_cannot_promote_failing_binding_to_done():
    # LLM hallucinates 'done' but the objective checks FAIL → veto to repair_impl.
    r = await CompletionJudge(_DecisionLLM("done")).run(_ctx(_state(passed=False)))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.IMPLEMENTATION


@pytest.mark.asyncio
async def test_open_ended_task_judge_is_primary():
    # No binding checks at all → the judge's 'done' STANDS (floor is empty).
    st = _state(passed=True, binding=False, how_to_validate="")
    r = await CompletionJudge(_DecisionLLM("done")).run(_ctx(st))
    assert r.branch == "done"
    assert isinstance(r.output, TaskCompleted)


@pytest.mark.asyncio
async def test_repair_impl_below_cap():
    r = await CompletionJudge(_DecisionLLM("repair_impl", reason="off-by-one")).run(
        _ctx(_state(passed=False)))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.IMPLEMENTATION
    assert "off-by-one" in r.verdict.hint


@pytest.mark.asyncio
async def test_repair_accept_routes_to_acceptance_layer():
    # The pipefail class: the check itself is broken → bubble to acceptance_oracle.
    r = await CompletionJudge(_DecisionLLM("repair_accept", reason="Illegal option pipefail")).run(
        _ctx(_state(passed=False)))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.ACCEPTANCE


@pytest.mark.asyncio
async def test_repair_plan_routes_to_plan_layer():
    r = await CompletionJudge(_DecisionLLM("repair_plan", reason="wrong files")).run(
        _ctx(_state(passed=False)))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_escalates_at_cap_when_failing():
    r = await CompletionJudge(_DecisionLLM("repair_impl")).run(
        _ctx(_state(passed=False, n_attempts=MAX_ATTEMPTS)))
    assert r.verdict.kind is VerdictKind.ESCALATE
    assert r.verdict.query is not None


@pytest.mark.asyncio
async def test_objective_pass_wins_at_cap_over_judge_demotion():
    # At the cap, a judge that keeps demoting a task whose objective checks PASS must
    # NOT abandon it — the objective floor accepts. (No infinite demotion of passing work.)
    r = await CompletionJudge(_DecisionLLM("repair_impl")).run(
        _ctx(_state(passed=True, n_attempts=MAX_ATTEMPTS)))
    assert r.branch == "done"
    assert isinstance(r.output, TaskCompleted)


def test_parse_rejects_unknown_verdict():
    j = CompletionJudge(llm=None)
    with pytest.raises(StructuredOutputError):
        j.parse('{"verdict": "DONE", "reason": "x"}')


@pytest.mark.asyncio
async def test_prompt_carries_observed_and_repair_accept_instruction():
    llm = _DecisionLLM("done")
    await CompletionJudge(llm).run(_ctx(_state(passed=True)))
    system = llm.seen[0]["content"].lower()
    user = llm.seen[-1]["content"]
    assert "repair_accept" in system          # the broken-check escape is offered
    assert "criterion-1" in user              # OBSERVED per-check results reach the judge
