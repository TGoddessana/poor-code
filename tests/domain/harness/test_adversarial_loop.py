import asyncio
import json
from pathlib import Path
import pytest

from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.graph import EdgeTable
from poor_code.domain.session.models import Layer
from poor_code.domain.harness.nodes.execution import (
    TaskSelector, EngGate, ValidationRunner, CompletionGate)

# This test drives the execution loop's inner nodes DIRECTLY (flat, with stubs), so it
# needs a local edge table carrying the inner edges — those edges moved out of the
# global route() into the implement_loop subgraph. Mirrors the old route.FORWARD inner
# rows + the loop's exit (task_selector 'done' → global_validator → reporter).
_LOCAL_EDGES = EdgeTable(
    forward={
        ("task_selector", "task"): "composer",
        ("task_selector", "done"): "global_validator",
        ("composer", None): "implementer",
        ("implementer", None): "eng_gate",
        ("eng_gate", None): "validator",
        ("validator", None): "validation_runner",
        ("validation_runner", "pass"): "completion_gate",
        ("validation_runner", "fail"): "failure_analyst",
        ("failure_analyst", None): "completion_gate",
        ("completion_gate", "done"): "task_selector",
        ("global_validator", "pass"): "reporter",
    },
    back_edges={Layer.IMPLEMENTATION: "implementer"},
)
route = _LOCAL_EDGES.route
from poor_code.domain.harness.nodes.composer import Composer
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.harness.nodes.validator import Validator, MAX_ADVERSARIAL_ROUNDS
from poor_code.domain.harness.nodes.failure_analyst import FailureAnalyst
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.write import WriteTool
from poor_code.domain.tool.edit import EditTool
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus)
from poor_code.provider.events import (
    TextDelta, ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason)


class AlwaysRepairLLM:
    """Implementer writes out.txt then stops; validator ALWAYS says repair_impl.
    The adversarial cap must force advance → runner passes → task done."""

    def __init__(self):
        # Toggle: True means next write-branch call emits the tool call,
        # False means it emits text + stop (so the implementer loop exits).
        self._writing = True

    async def stream(self, messages, tools, response_format=None):
        name = tools[0]["function"]["name"]
        if name == "write":
            if self._writing:
                # Round 1: emit the write tool call
                self._writing = False
                yield ToolCallStarted(call_id="w", name="write")
                yield ToolCallInputDelta(call_id="w",
                                         json_delta='{"path":"out.txt","content":"ok"}')
                yield ToolCallEnded(call_id="w")
                yield FinishedReason(reason="tool_calls")
            else:
                # Round 2: no tool call → implementer loop exits
                self._writing = True
                yield TextDelta(text="done")
                yield FinishedReason(reason="stop")
            return
        if name == "judge":
            yield ToolCallStarted(call_id="j", name="judge")
            yield ToolCallInputDelta(call_id="j",
                                     json_delta=json.dumps({"verdict": "repair_impl", "hint": "more"}))
            yield ToolCallEnded(call_id="j")
            yield FinishedReason(reason="tool_calls")
            return
        yield TextDelta(text="x")
        yield FinishedReason(reason="stop")


def _registry(cwd, llm):
    reg = NodeRegistry()
    reg.register(TaskSelector())
    reg.register(Composer())
    reg.register(Implementer(llm, cwd=cwd,
                             tools=ToolRegistry([WriteTool(), EditTool(), BashTool()])))
    reg.register(EngGate())
    reg.register(Validator(llm))
    reg.register(ValidationRunner(cwd=cwd))
    reg.register(FailureAnalyst(llm))
    reg.register(CompletionGate())

    class _PassGV:
        name = "global_validator"
        async def run(self, ctx):
            from poor_code.domain.harness.node import NodeResult
            return NodeResult(branch="pass")
    reg.register(_PassGV())
    return reg


@pytest.mark.asyncio
async def test_adversarial_loop_caps_and_completes(tmp_path):
    reg = _registry(tmp_path, AlwaysRepairLLM())
    visited = []
    driver = Driver(reg, route, on_step=lambda s: visited.append(s.cursor.current_node))
    start = SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("out.txt",)),
                              how_to_validate="test -f out.txt"),)),
        cursor=Cursor(phase=Phase.PLANNING, current_node="task_selector"))
    final = await driver.run(start, asyncio.Event())

    assert final.cursor.current_node == "reporter"           # terminated, did not loop forever
    assert final.plan.tasks[0].status is TaskStatus.DONE
    # validator pushed back exactly MAX_ADVERSARIAL_ROUNDS times before forced advance
    assert final.plan.tasks[0].attempts[-1].adversarial_rounds == MAX_ADVERSARIAL_ROUNDS

    # Traversal proof: implementer and validator each run once per adversarial round,
    # and the loop terminates at reporter.
    assert visited.count("implementer") == MAX_ADVERSARIAL_ROUNDS + 1
    assert visited.count("validator") == MAX_ADVERSARIAL_ROUNDS + 1
    assert visited[-1] == "reporter"
