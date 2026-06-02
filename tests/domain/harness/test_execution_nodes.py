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


@pytest.mark.asyncio
async def test_task_selector_resumes_active_task():
    """A plan whose only task is ACTIVE must be re-selected (resume safety)."""
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p", status=TaskStatus.ACTIVE),))
    r = await TaskSelector().run(_ctx(SessionState(plan=plan)))
    assert isinstance(r.output, SelectedTask) and r.output.task_id == "t1"
    assert r.branch == "task"


from poor_code.domain.harness.nodes.execution import EngGate
from poor_code.domain.session.models import (
    Attempt, ChangeRecord, EditScope, VerdictKind, Layer,
)


def _state_with_attempt(attempt, *, editable=("src/a.py",), forbidden=()):
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p",
                            edit_scope=EditScope(editable=editable, forbidden=forbidden),
                            attempts=(attempt,)),))
    cur = Cursor(phase=Phase.IMPLEMENTING, current_node="eng_gate", task_id="t1",
                 attempt_id=attempt.id)
    return SessionState(plan=plan, cursor=cur)


@pytest.mark.asyncio
async def test_eng_gate_advances_on_in_scope_patch():
    a = Attempt(id="a1", patch=ChangeRecord(files=("src/a.py",), diff="@@"))
    r = await EngGate().run(_ctx(_state_with_attempt(a)))
    assert r.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_eng_gate_repairs_on_missing_patch():
    a = Attempt(id="a1", patch=None)
    r = await EngGate().run(_ctx(_state_with_attempt(a)))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.IMPLEMENTATION


@pytest.mark.asyncio
async def test_eng_gate_repairs_on_out_of_scope_edit():
    a = Attempt(id="a1", patch=ChangeRecord(files=("src/forbidden.py",), diff="@@"))
    r = await EngGate().run(_ctx(_state_with_attempt(a, editable=("src/a.py",),
                                                     forbidden=("src/forbidden.py",))))
    assert r.verdict.kind is VerdictKind.REPAIR


from pathlib import Path
from poor_code.domain.harness.nodes.execution import ValidationRunner
from poor_code.domain.session.models import ValidationResult


def _runner_state(how_to_validate, tmp_path):
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p",
                            how_to_validate=how_to_validate,
                            attempts=(Attempt(id="a1"),)),))
    cur = Cursor(phase=Phase.IMPLEMENTING, current_node="validation_runner",
                 task_id="t1", attempt_id="a1")
    return SessionState(plan=plan, cursor=cur)


@pytest.mark.asyncio
async def test_validation_runner_pass(tmp_path):
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(_runner_state("true", tmp_path)))
    assert isinstance(r.output, ValidationResult)
    assert r.output.passed is True and r.output.exit_code == 0
    assert r.branch == "pass"


@pytest.mark.asyncio
async def test_validation_runner_fail(tmp_path):
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(_runner_state("false", tmp_path)))
    assert r.output.passed is False and r.output.exit_code != 0
    assert r.branch == "fail"


@pytest.mark.asyncio
async def test_validation_runner_runs_in_cwd(tmp_path):
    (tmp_path / "marker.txt").write_text("hi")
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(_runner_state("test -f marker.txt", tmp_path)))
    assert r.output.passed is True


@pytest.mark.asyncio
async def test_validation_runner_cancel_mid_run(tmp_path):
    """Cancel event set mid-run must kill the subprocess and raise CancelledError
    well before the 120s timeout. Uses asyncio.wait_for with a 10s bound."""
    cancel = asyncio.Event()
    state = _runner_state("sleep 30", tmp_path)
    ctx = NodeContext(state=state, cancel=cancel)

    async def _run_and_cancel():
        # Set cancel shortly after the subprocess is spawned
        async def _set_cancel():
            await asyncio.sleep(0.1)
            cancel.set()

        asyncio.create_task(_set_cancel())
        await ValidationRunner(cwd=tmp_path).run(ctx)

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(_run_and_cancel(), timeout=10)


from poor_code.domain.harness.nodes.execution import CompletionGate, MAX_ATTEMPTS
from poor_code.domain.session.models import TaskCompleted


def _completion_state(attempts):
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p", attempts=tuple(attempts)),))
    cur = Cursor(phase=Phase.IMPLEMENTING, current_node="completion_gate",
                 task_id="t1", attempt_id=attempts[-1].id)
    return SessionState(plan=plan, cursor=cur)


def _passed(aid):
    return Attempt(id=aid, run_result=ValidationResult(command="true", exit_code=0, passed=True))


def _failed(aid):
    return Attempt(id=aid, run_result=ValidationResult(command="false", exit_code=1, passed=False))


@pytest.mark.asyncio
async def test_completion_gate_done_on_pass():
    r = await CompletionGate().run(_ctx(_completion_state([_passed("a1")])))
    assert isinstance(r.output, TaskCompleted) and r.output.task_id == "t1"
    assert r.branch == "done"


@pytest.mark.asyncio
async def test_completion_gate_repairs_below_cap():
    r = await CompletionGate().run(_ctx(_completion_state([_failed("a1")])))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.IMPLEMENTATION


@pytest.mark.asyncio
async def test_completion_gate_escalates_at_cap():
    attempts = [_failed(f"a{i}") for i in range(MAX_ATTEMPTS)]
    r = await CompletionGate().run(_ctx(_completion_state(attempts)))
    assert r.verdict.kind is VerdictKind.ESCALATE
    assert r.verdict.query is not None


from poor_code.domain.harness.route import FORWARD


def test_execution_forward_edges_present():
    assert FORWARD[("plan_gate", None)] == "task_selector"
    assert FORWARD[("task_selector", "task")] == "composer"
    assert FORWARD[("task_selector", "done")] == "global_validator"
    assert FORWARD[("composer", None)] == "implementer"
    assert FORWARD[("implementer", None)] == "eng_gate"
    assert FORWARD[("eng_gate", None)] == "validator"
    assert FORWARD[("validator", None)] == "validation_runner"
    assert FORWARD[("validation_runner", "pass")] == "completion_gate"
    assert FORWARD[("validation_runner", "fail")] == "failure_analyst"
    assert FORWARD[("failure_analyst", None)] == "completion_gate"
    assert FORWARD[("completion_gate", "done")] == "task_selector"
    assert FORWARD[("global_validator", "pass")] == "reporter"


def test_build_registry_has_code_nodes():
    from datetime import UTC, datetime
    from poor_code.domain.project_map.models import ProjectMap
    from poor_code.domain.harness import build_default_registry

    class _LLM:
        async def stream(self, messages, tools):
            if False:
                yield None

    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    reg = build_default_registry(llm=_LLM(), project_map=pm)
    for n in ("task_selector", "eng_gate", "validation_runner", "completion_gate"):
        assert reg.get(n) is not None
        assert reg.get(n).name == n


@pytest.mark.asyncio
async def test_run_shell_returns_exit_code_and_output(tmp_path):
    from poor_code.domain.harness.nodes.execution import run_shell
    import asyncio as _a
    code, out = await run_shell("echo hello", tmp_path, _a.Event())
    assert code == 0 and "hello" in out
    code, _ = await run_shell("exit 7", tmp_path, _a.Event())
    assert code == 7
