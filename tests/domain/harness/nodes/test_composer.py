import asyncio
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.composer import Composer
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
    CodeContext, CodeRef, TaskContext)


def _state(understanding):
    return SessionState(
        understanding=understanding,
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("src/auth.py",),
                                                   readonly=("src/util.py",)),
                              how_to_validate="pytest", status=TaskStatus.ACTIVE),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="composer", task_id="t1"))


@pytest.mark.asyncio
async def test_composer_projects_in_scope_refs():
    cc = CodeContext(candidates=(
        CodeRef(file="src/auth.py", symbol="login"),   # in editable → kept
        CodeRef(file="src/util.py", symbol="helper"),  # in readonly → kept
        CodeRef(file="src/other.py", symbol="nope"),   # out of scope → dropped
    ))
    res = await Composer().run(NodeContext(state=_state(cc), cancel=asyncio.Event()))
    assert isinstance(res.output, TaskContext)
    files = {r.file for r in res.output.refs}
    assert files == {"src/auth.py", "src/util.py"}
    assert res.output.snippet is None


@pytest.mark.asyncio
async def test_composer_handles_no_understanding():
    res = await Composer().run(NodeContext(state=_state(None), cancel=asyncio.Event()))
    assert isinstance(res.output, TaskContext)
    assert res.output.refs == ()
