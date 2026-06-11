import asyncio
import json
import pytest

from poor_code.domain.harness.node import NodeContext, StructuredOutputError
from poor_code.domain.harness.nodes.failure_analyst import FailureAnalyst
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
    Attempt, ChangeRecord, ValidationResult, FeedbackEntry)
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class _FeedbackLLM:
    def __init__(self, payload):
        self._args = json.dumps(payload)
    async def stream(self, messages, tools, response_format=None):
        yield ToolCallStarted(call_id="f1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="f1", json_delta=self._args)
        yield ToolCallEnded(call_id="f1")
        yield FinishedReason(reason="tool_calls")


def _state():
    att = Attempt(id="t1-a1", patch=ChangeRecord(files=("a.py",), diff="d"),
                  run_result=ValidationResult(command="pytest", exit_code=1,
                                              passed=False, output="AssertionError"))
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("a.py",)),
                              how_to_validate="pytest", status=TaskStatus.ACTIVE,
                              attempts=(att,)),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="failure_analyst",
                      task_id="t1", attempt_id="t1-a1"))


@pytest.mark.asyncio
async def test_failure_analyst_emits_feedback_entry():
    llm = _FeedbackLLM({"failure_type": "logic_error", "symptom": "assertion failed",
                        "prevention_hint": "check the boundary"})
    res = await FailureAnalyst(llm).run(NodeContext(state=_state(), cancel=asyncio.Event()))
    fe = res.output
    assert isinstance(fe, FeedbackEntry)
    assert fe.failure_type == "logic_error"
    assert fe.task_ref == "t1"        # node stamps the active task id


def test_empty_feedback_is_rejected():
    fa = FailureAnalyst(llm=None)
    with pytest.raises(StructuredOutputError):
        fa.parse("{}")


def test_blank_lesson_is_rejected():
    fa = FailureAnalyst(llm=None)
    with pytest.raises(StructuredOutputError):
        fa.parse('{"failure_type": "", "symptom": "", "prevention_hint": ""}')
