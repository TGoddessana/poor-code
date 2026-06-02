import asyncio
import pytest
from poor_code.domain.harness.node import NodeResult, NodeContext
from poor_code.domain.harness.route import route, FORWARD
from poor_code.domain.session.models import SessionState


def test_noderesult_has_branch_default_none():
    assert NodeResult().branch is None


def test_route_uses_explicit_branch(monkeypatch):
    monkeypatch.setitem(FORWARD, ("zzz_test_node", "left"), "target_left")
    r = NodeResult(branch="left")
    assert route("zzz_test_node", r, SessionState()) == "target_left"


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


from poor_code.domain.harness.nodes.execution import TaskSelector
from poor_code.domain.session.models import (
    Plan, Task, Dependency, TaskStatus, Cursor, Phase, SelectedTask,
)


@pytest.mark.asyncio
async def test_task_selector_picks_first_pending():
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p"),
                       Task(id="t2", title="B", purpose="p")))
    r = await TaskSelector().run(_ctx(SessionState(plan=plan)))
    assert isinstance(r.output, SelectedTask) and r.output.task_id == "t1"
    assert r.branch == "task"


@pytest.mark.asyncio
async def test_task_selector_respects_deps():
    plan = Plan(
        tasks=(Task(id="t1", title="A", purpose="p", status=TaskStatus.PENDING),
               Task(id="t2", title="B", purpose="p", status=TaskStatus.PENDING)),
        deps=(Dependency(task_id="t2", depends_on="t1"),),
    )
    # t1 not done yet → only t1 is eligible
    r = await TaskSelector().run(_ctx(SessionState(plan=plan)))
    assert r.output.task_id == "t1"


@pytest.mark.asyncio
async def test_task_selector_skips_done_and_picks_dependent():
    plan = Plan(
        tasks=(Task(id="t1", title="A", purpose="p", status=TaskStatus.DONE),
               Task(id="t2", title="B", purpose="p", status=TaskStatus.PENDING)),
        deps=(Dependency(task_id="t2", depends_on="t1"),),
    )
    r = await TaskSelector().run(_ctx(SessionState(plan=plan)))
    assert r.output.task_id == "t2"


@pytest.mark.asyncio
async def test_task_selector_done_branch_when_no_pending():
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p", status=TaskStatus.DONE),))
    r = await TaskSelector().run(_ctx(SessionState(plan=plan)))
    assert r.output is None and r.branch == "done"
