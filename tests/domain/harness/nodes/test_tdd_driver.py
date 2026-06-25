import asyncio
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.session.models import (
    Step, StepKind, Task, EditScope, SessionState, Plan, Cursor, Phase, TaskStatus)
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.write import WriteTool
from poor_code.domain.tool.edit import EditTool


def _tools():
    return ToolRegistry([WriteTool(), EditTool(), BashTool()])


def _impl(tmp_path, llm=None):
    from tests.domain.harness.nodes.test_implementer import _WriteThenStopLLM
    return Implementer(llm or _WriteThenStopLLM(), cwd=tmp_path, tools=_tools())


def _state_with_steps(steps):
    task = Task(id="t1", title="add f", purpose="p",
                edit_scope=EditScope(editable=("impl.py", "test_x.py")),
                how_to_validate="true", status=TaskStatus.ACTIVE, steps=tuple(steps))
    return SessionState(
        plan=Plan(tasks=(task,)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t1"))


def test_gate_command_prefers_step_run_then_how_to_validate(tmp_path):
    impl = _impl(tmp_path)
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("x.py",)), how_to_validate="pytest -q")
    with_run = Step(id="s1", kind=StepKind.IMPL, file="x.py", run="echo hi")
    no_run = Step(id="s2", kind=StepKind.IMPL, file="x.py", run="")
    assert impl._gate_command(with_run, task) == "echo hi"
    assert impl._gate_command(no_run, task) == "pytest -q"


@pytest.mark.asyncio
async def test_run_gate_returns_exit_code(tmp_path):
    impl = _impl(tmp_path)
    ctx = NodeContext(state=None, cancel=asyncio.Event())
    assert await impl._run_gate("true", ctx) == 0
    assert await impl._run_gate("false", ctx) != 0
    assert await impl._run_gate("", ctx) == 0   # no gate command → non-blocking pass


def test_step_seed_test_kind_forbids_impl_and_carries_body(tmp_path):
    impl = _impl(tmp_path)
    step = Step(id="s1", kind=StepKind.TEST, file="test_x.py",
                body="def test_f():\n    assert f() == 1", run="true")
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("test_x.py",)), how_to_validate="true")
    seed = impl._step_seed(SessionState(), task, step, feedback="")
    blob = " ".join(m["content"] for m in seed)
    assert "def test_f()" in blob          # planner draft body is handed over
    assert "do not write the implementation" in blob.lower()


def test_step_seed_impl_kind_mentions_make_test_pass(tmp_path):
    impl = _impl(tmp_path)
    step = Step(id="s2", kind=StepKind.IMPL, file="impl.py",
                body="def f():\n    return 1", run="true")
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("impl.py",)), how_to_validate="true")
    seed = impl._step_seed(SessionState(), task, step, feedback="prev output here")
    blob = " ".join(m["content"] for m in seed)
    assert "make the test pass" in blob.lower()
    assert "prev output here" in blob       # feedback is threaded into the seed


@pytest.mark.asyncio
async def test_author_step_writes_file_to_tree(tmp_path):
    from tests.domain.harness.nodes.test_implementer import _WriteThenStopLLM
    impl = _impl(tmp_path, llm=_WriteThenStopLLM(content="data"))
    await impl._snapshot.init()
    step = Step(id="s1", kind=StepKind.TEST, file="out.txt", body="data", run="true")
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("out.txt",)), how_to_validate="true")
    await impl._author_step(SessionState(), task, step, NodeContext(
        state=SessionState(), cancel=asyncio.Event()))
    assert (tmp_path / "out.txt").read_text() == "data"
