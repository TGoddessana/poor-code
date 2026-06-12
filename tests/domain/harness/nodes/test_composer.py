import asyncio
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.composer import Composer
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
    CodeContext, CodeRef, FileExcerpt, TaskContext)


def _state(understanding):
    return SessionState(
        understanding=understanding,
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("src/auth.py",),
                                                   readonly=("src/util.py",)),
                              how_to_validate="pytest", status=TaskStatus.ACTIVE),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="composer", task_id="t1"))


@pytest.mark.asyncio
async def test_composer_passes_all_candidates_not_just_scope():
    # T1: the implementer needs the WHOLE picture, marked — not a scope-filtered subset.
    cc = CodeContext(candidates=(
        CodeRef(file="src/auth.py", symbol="login"),
        CodeRef(file="src/util.py", symbol="helper"),
        CodeRef(file="src/other.py", symbol="nope"),
    ))
    res = await Composer().run(NodeContext(state=_state(cc), cancel=asyncio.Event()))
    assert isinstance(res.output, TaskContext)
    assert {r.file for r in res.output.refs} == {"src/auth.py", "src/util.py", "src/other.py"}


@pytest.mark.asyncio
async def test_composer_injects_excerpt_bodies_with_role_labels():
    cc = CodeContext(
        candidates=(CodeRef(file="src/auth.py"), CodeRef(file="src/util.py")),
        excerpts=(
            FileExcerpt(path="src/auth.py", text="def login(): return 1"),
            FileExcerpt(path="src/util.py", text="def helper(): return 2"),
        ))
    res = await Composer().run(NodeContext(state=_state(cc), cancel=asyncio.Event()))
    snip = res.output.snippet
    assert snip is not None
    assert "def login(): return 1" in snip          # the body reaches the context
    assert "src/auth.py [EDITABLE]" in snip          # editable file labeled
    assert "src/util.py [READONLY]" in snip          # readonly file labeled


@pytest.mark.asyncio
async def test_composer_clips_long_excerpt_body():
    big = "x" * 5000
    cc = CodeContext(candidates=(CodeRef(file="src/auth.py"),),
                     excerpts=(FileExcerpt(path="src/auth.py", text=big),))
    res = await Composer().run(NodeContext(state=_state(cc), cancel=asyncio.Event()))
    assert "truncated" in res.output.snippet
    assert res.output.snippet.count("x") <= 1800


@pytest.mark.asyncio
async def test_composer_lists_confusers_as_anti_targets():
    cc = CodeContext(
        candidates=(CodeRef(file="src/auth.py"),),
        confusers=(CodeRef(file="src/auth_legacy.py", symbol="old_login"),))
    res = await Composer().run(NodeContext(state=_state(cc), cancel=asyncio.Event()))
    snip = res.output.snippet
    assert "NOT these" in snip
    assert "src/auth_legacy.py::old_login" in snip


@pytest.mark.asyncio
async def test_composer_handles_no_understanding():
    res = await Composer().run(NodeContext(state=_state(None), cancel=asyncio.Event()))
    assert isinstance(res.output, TaskContext)
    assert res.output.refs == ()
    assert res.output.snippet is None
