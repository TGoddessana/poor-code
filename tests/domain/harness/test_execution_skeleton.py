# tests/domain/harness/test_execution_skeleton.py
import asyncio
from pathlib import Path
import pytest

from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route
from poor_code.domain.harness.nodes.execution import (
    TaskSelector, EngGate, ValidationRunner, CompletionGate, MAX_ATTEMPTS,
)
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
    Attempt, ChangeRecord, Verdict, VerdictKind,
)


class _Passthrough:
    """Stub composer/validator: advance with no state change."""
    def __init__(self, name): self.name = name
    async def run(self, ctx): return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))


class _StubImplementer:
    """Writes the task's target file in cwd, returns an in-scope Attempt."""
    name = "implementer"
    def __init__(self, cwd, action): self._cwd, self._action = cwd, action
    async def run(self, ctx):
        task = next(t for t in ctx.state.plan.tasks if t.id == ctx.state.cursor.task_id)
        target = task.edit_scope.editable[0]
        self._action(self._cwd, target)
        aid = f"{task.id}-att{len(task.attempts)+1}"
        return NodeResult(output=Attempt(id=aid, patch=ChangeRecord(files=(target,), diff="x")))


class _StubGlobalValidator:
    name = "global_validator"
    async def run(self, ctx): return NodeResult(branch="pass")


def _registry(cwd, implementer):
    reg = NodeRegistry()
    reg.register(TaskSelector())
    reg.register(_Passthrough("composer"))
    reg.register(implementer)
    reg.register(EngGate())
    reg.register(_Passthrough("validator"))
    reg.register(ValidationRunner(cwd=cwd))
    reg.register(_Passthrough("failure_analyst"))   # advance → completion_gate re-evaluates
    reg.register(CompletionGate())
    reg.register(_StubGlobalValidator())
    return reg


def _plan_two_tasks():
    return Plan(tasks=(
        Task(id="t1", title="make a", purpose="p",
             edit_scope=EditScope(editable=("a.txt",)), how_to_validate="test -f a.txt"),
        Task(id="t2", title="make b", purpose="p",
             edit_scope=EditScope(editable=("b.txt",)), how_to_validate="test -f b.txt"),
    ))


@pytest.mark.asyncio
async def test_skeleton_runs_two_tasks_to_terminal(tmp_path):
    def write(cwd, target): (cwd / target).write_text("ok")
    reg = _registry(tmp_path, _StubImplementer(tmp_path, write))
    visited = []
    driver = Driver(reg, route, on_step=lambda s: visited.append(s.cursor.current_node))
    start = SessionState(plan=_plan_two_tasks(),
                         cursor=Cursor(phase=Phase.PLANNING, current_node="task_selector"))
    final = await driver.run(start, asyncio.Event())

    # both tasks marked DONE, graph reached the unregistered 'reporter' park (terminal)
    assert all(t.status is TaskStatus.DONE for t in final.plan.tasks)
    assert final.cursor.current_node == "reporter"
    assert (tmp_path / "a.txt").exists() and (tmp_path / "b.txt").exists()


@pytest.mark.asyncio
async def test_skeleton_terminates_on_persistent_failure(tmp_path):
    # implementer that never creates the file → validation always fails → cap → escalate
    def noop(cwd, target): pass
    reg = _registry(tmp_path, _StubImplementer(tmp_path, noop))
    driver = Driver(reg, route)
    start = SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("a.txt",)),
                              how_to_validate="test -f a.txt"),)),
        cursor=Cursor(phase=Phase.PLANNING, current_node="task_selector"))
    final = await driver.run(start, asyncio.Event())

    # escalated to user (cap hit) — terminated, did not loop forever
    assert final.cursor.current_node == "user"
    assert len(final.plan.tasks[0].attempts) == MAX_ATTEMPTS
