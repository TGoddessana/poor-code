import asyncio
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.session.models import Step, StepKind, Task, EditScope
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.write import WriteTool
from poor_code.domain.tool.edit import EditTool


def _tools():
    return ToolRegistry([WriteTool(), EditTool(), BashTool()])


def _impl(tmp_path, llm=None):
    from tests.domain.harness.nodes.test_implementer import _WriteThenStopLLM
    return Implementer(llm or _WriteThenStopLLM(), cwd=tmp_path, tools=_tools())


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
