"""Integration test for the self-confirming-block defense.

The Validator now RUNS the global acceptance checks for real (run_shell) and judges
from OBSERVED reality, not the implementer's narrative. This test proves the WIRING:
when an attempt's patch CLAIMS success but the acceptance command FAILS when actually
executed, the validator surfaces it as OBSERVED FAIL and the judge returns repair_impl
(NOT advance). The SAME setup with a PASSING command advances — so it is the real
command execution, not the patch text, that drives the outcome.

run_shell is NOT mocked here (that is the whole point): the Validator is constructed
with cwd=tmp_path and the acceptance check is a real shell command against a real file
on disk. The judge LLM is the only stub, and it decides solely from the OBSERVED block
the validator hands it — so a green run can only happen if the command really passed.
"""
import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.validator import Validator
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Attempt, ChangeRecord, Cursor, EditScope,
    Phase, Plan, SessionState, Task, VerdictKind,
)
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason)


class _ObservedDrivenJudge:
    """Stub judge that decides from the OBSERVED block the validator built — exactly the
    wiring under test. If the real run surfaced any 'FAIL', it returns repair_impl and
    cites it; if everything is 'PASS', it advances. So the verdict can only be 'advance'
    when the acceptance command actually exited 0 on disk."""

    def __init__(self) -> None:
        self.saw_observed: str | None = None

    async def stream(self, messages, tools, response_format=None):
        blob = "\n".join(m["content"] for m in messages)
        # Capture the OBSERVED section so the test can assert the command really ran.
        self.saw_observed = blob
        observed_failed = "-> FAIL" in blob
        verdict = "repair_impl" if observed_failed else "advance"
        hint = "acceptance check failed when run" if observed_failed else ""
        yield ToolCallStarted(call_id="j", name="judge")
        yield ToolCallInputDelta(
            call_id="j", json_delta=json.dumps({"verdict": verdict, "hint": hint}))
        yield ToolCallEnded(call_id="j")
        yield FinishedReason(reason="tool_calls")


def _state(*, command: str) -> SessionState:
    # The attempt's patch CLAIMS it implemented the feature correctly. Whether that is
    # true is decided by RUNNING `command`, not by trusting this diff.
    attempt = Attempt(
        id="a1",
        patch=ChangeRecord(
            files=("out.txt",),
            diff="+ implemented fib(10)=55 correctly; out.txt now contains 55"))
    task = Task(id="t1", title="fib", purpose="",
                edit_scope=EditScope(editable=("out.txt",)),
                attempts=(attempt,))
    return SessionState(
        plan=Plan(tasks=(task,), plan_md="## t1: out.txt — fib handler"),
        acceptance=AcceptanceSpec(checks=(
            AcceptanceCheck(criterion="n=10 -> 55", command=command),
        )),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="validator",
                      task_id="t1", attempt_id="a1"))


def _ctx(state: SessionState) -> NodeContext:
    return NodeContext(state=state, cancel=asyncio.Event())


@pytest.mark.asyncio
async def test_failing_acceptance_command_yields_repair_impl(tmp_path):
    # The work tree has out.txt containing "34" — the feature is NOT actually done.
    (tmp_path / "out.txt").write_text("34\n")
    # The real acceptance command demands out.txt to contain exactly "55"; it FAILS.
    command = f"grep -qx 55 {tmp_path / 'out.txt'}"

    judge = _ObservedDrivenJudge()
    node = Validator(judge, cwd=tmp_path)            # REAL run_shell against tmp_path
    result = await node.run(_ctx(_state(command=command)))

    # The validator actually ran the failing command and surfaced it as OBSERVED FAIL ...
    assert judge.saw_observed is not None
    assert "OBSERVED" in judge.saw_observed
    assert "-> FAIL" in judge.saw_observed
    # ... so the judge (reading reality, not the patch's claim) chose to repair, not advance.
    assert result.verdict.kind is VerdictKind.REPAIR
    assert result.verdict.hint  # cites the observed failure


@pytest.mark.asyncio
async def test_passing_acceptance_command_yields_advance(tmp_path):
    # Same setup, but now the work tree really satisfies the check: out.txt contains "55".
    (tmp_path / "out.txt").write_text("55\n")
    command = f"grep -qx 55 {tmp_path / 'out.txt'}"

    judge = _ObservedDrivenJudge()
    node = Validator(judge, cwd=tmp_path)            # REAL run_shell against tmp_path
    result = await node.run(_ctx(_state(command=command)))

    # The command really passed → OBSERVED PASS → the same judge advances.
    assert judge.saw_observed is not None
    assert "-> PASS" in judge.saw_observed
    assert "-> FAIL" not in judge.saw_observed
    assert result.verdict.kind is VerdictKind.ADVANCE
