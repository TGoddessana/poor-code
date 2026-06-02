import asyncio
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
    Attempt, ValidationResult, ChangeRecord)
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.write import WriteTool
from poor_code.domain.tool.edit import EditTool
from poor_code.domain.tool.bash import BashTool
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class _WriteThenStopLLM:
    """Round 1: write `out.txt`. Round 2: stop (no tool calls)."""
    def __init__(self, content="hi"):
        self.calls = 0
        self._content = content
    async def stream(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            yield ToolCallStarted(call_id="w1", name="write")
            yield ToolCallInputDelta(
                call_id="w1",
                json_delta='{"path":"out.txt","content":"%s"}' % self._content)
            yield ToolCallEnded(call_id="w1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield TextDelta(text="done")
            yield FinishedReason(reason="stop")


def _tools():
    return ToolRegistry([WriteTool(), EditTool(), BashTool()])


def _state(attempts=()):
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("out.txt",)),
                              how_to_validate="test -f out.txt",
                              status=TaskStatus.ACTIVE, attempts=attempts),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t1"))


@pytest.mark.asyncio
async def test_implementer_writes_file_and_emits_attempt(tmp_path):
    node = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert (tmp_path / "out.txt").read_text() == "hi"
    att = res.output
    assert isinstance(att, Attempt)
    assert att.adversarial_rounds == 0
    assert "out.txt" in att.patch.files
    assert "out.txt" in att.patch.diff


@pytest.mark.asyncio
async def test_implementer_refines_in_place_when_latest_has_no_run_result(tmp_path):
    node = Implementer(_WriteThenStopLLM(content="v2"), cwd=tmp_path, tools=_tools())
    prior = Attempt(id="t1-a1", patch=ChangeRecord(files=("out.txt",), diff="old"),
                    adversarial_rounds=0, run_result=None)
    res = await node.run(NodeContext(state=_state(attempts=(prior,)), cancel=asyncio.Event()))
    assert res.output.id == "t1-a1"               # same id → in-place refine
    assert res.output.adversarial_rounds == 1


@pytest.mark.asyncio
async def test_implementer_starts_new_attempt_after_runner_failure(tmp_path):
    node = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    failed = Attempt(id="t1-a1", patch=ChangeRecord(files=("out.txt",), diff="x"),
                     adversarial_rounds=2,
                     run_result=ValidationResult(command="c", exit_code=1, passed=False))
    res = await node.run(NodeContext(state=_state(attempts=(failed,)), cancel=asyncio.Event()))
    assert res.output.id == "t1-a2"               # new attempt id
    assert res.output.adversarial_rounds == 0
