import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.validator import Validator
import poor_code.domain.harness.nodes.validator as validator_mod
from poor_code.domain.session.models import (
    SessionState, Plan, Task, Attempt, ChangeRecord, EditScope, Cursor, Phase,
    AcceptanceSpec, AcceptanceCheck, VerdictKind,
)
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason)


class _JudgeLLM:
    """Stub LLM: the validator's forced 'judge' tool call always returns advance."""

    async def stream(self, messages, tools, response_format=None):
        yield ToolCallStarted(call_id="j", name="judge")
        yield ToolCallInputDelta(call_id="j",
                                 json_delta=json.dumps({"verdict": "advance", "hint": ""}))
        yield ToolCallEnded(call_id="j")
        yield FinishedReason(reason="tool_calls")


def _state():
    attempt = Attempt(id="a1", patch=ChangeRecord(files=("server.py",), diff="+x"))
    task = Task(id="t1", title="fib", purpose="",
                edit_scope=EditScope(editable=("server.py",)),
                attempts=(attempt,))
    return SessionState(
        plan=Plan(tasks=(task,), plan_md="## t1: server.py — fib handler"),
        acceptance=AcceptanceSpec(checks=(
            AcceptanceCheck(criterion="n=10 -> 55", command="cmd_a"),
            AcceptanceCheck(criterion="n=1 -> 1", command="cmd_b"),
        )),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="validator",
                      task_id="t1", attempt_id="a1"))


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_validator_runs_all_acceptance_checks(tmp_path, monkeypatch):
    calls = []

    async def fake_run_shell(command, cwd, cancel, timeout=120):
        calls.append(command)
        return 0, "ok"

    monkeypatch.setattr(validator_mod, "run_shell", fake_run_shell)
    node = Validator(_JudgeLLM(), cwd=tmp_path)
    await node.run(_ctx(_state()))
    assert calls == ["cmd_a", "cmd_b"]


@pytest.mark.asyncio
async def test_validator_records_check_results_on_attempt(tmp_path, monkeypatch):
    async def fake_run_shell(command, cwd, cancel, timeout=120):
        return (0 if command == "cmd_a" else 1), "out"

    monkeypatch.setattr(validator_mod, "run_shell", fake_run_shell)
    node = Validator(_JudgeLLM(), cwd=tmp_path)
    state = _state()
    result = await node.run(_ctx(state))

    # advance verdict, and the returned output records the observed results
    assert result.verdict.kind is VerdictKind.ADVANCE
    new_state = result.output.apply_to(state)
    recorded = new_state.plan.tasks[0].attempts[-1].check_results
    assert recorded == (("n=10 -> 55", True), ("n=1 -> 1", False))


@pytest.mark.asyncio
async def test_validator_observed_block_in_messages(tmp_path):
    node = Validator(_JudgeLLM(), cwd=tmp_path)
    node._observed = [("n=10 -> 55", True, "ok"), ("n=1 -> 1", False, "boom")]
    msgs = node.build_messages(_state())
    blob = "\n".join(m["content"] for m in msgs)
    assert "OBSERVED" in blob
    assert "PASS" in blob and "FAIL" in blob
    assert "n=10 -> 55" in blob and "n=1 -> 1" in blob
