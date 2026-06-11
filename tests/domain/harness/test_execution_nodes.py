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
async def test_eng_gate_repairs_on_forbidden_edit():
    a = Attempt(id="a1", patch=ChangeRecord(files=("src/forbidden.py",), diff="@@"))
    r = await EngGate().run(_ctx(_state_with_attempt(a, editable=("src/a.py",),
                                                     forbidden=("src/forbidden.py",))))
    assert r.verdict.kind is VerdictKind.REPAIR


@pytest.mark.asyncio
async def test_eng_gate_advances_on_edit_outside_editable_when_not_forbidden():
    # Scope appropriateness is now the validator's (semantic) judgment, not a mechanical
    # allowlist. eng_gate only blocks forbidden paths and empty patches; a legitimate
    # edit outside the declared editable (e.g. the task's own test file) advances to the
    # reviewer, who decides if it fits the task. This is what unblocked astropy-2: the
    # implementer edited test_qdp.py (not in editable) and the old gate killed it.
    a = Attempt(id="a1", patch=ChangeRecord(files=("tests/test_a.py",), diff="@@"))
    r = await EngGate().run(_ctx(_state_with_attempt(a, editable=("src/a.py",))))
    assert r.verdict.kind is VerdictKind.ADVANCE


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


from poor_code.domain.session.models import AcceptanceSpec, AcceptanceCheck


def _accept_runner_state(*, prior_check_results=(), how_to_validate=""):
    """Active task t1 with two prior attempts: a1 (the baseline carrying
    prior_check_results) and a2 (the cursor's current attempt being validated now)."""
    plan = Plan(tasks=(Task(
        id="t1", title="A", purpose="p", how_to_validate=how_to_validate,
        attempts=(Attempt(id="a1", check_results=tuple(prior_check_results)),
                  Attempt(id="a2"))),))
    cur = Cursor(phase=Phase.IMPLEMENTING, current_node="validation_runner",
                 task_id="t1", attempt_id="a2")
    spec = AcceptanceSpec(checks=(
        AcceptanceCheck(criterion="A", command="cmd-a"),
        AcceptanceCheck(criterion="B", command="cmd-b")))
    return SessionState(plan=plan, cursor=cur, acceptance=spec)


@pytest.mark.asyncio
async def test_validation_runner_passes_when_no_regression(monkeypatch, tmp_path):
    async def fake_run_shell(command, cwd, cancel, *a, **k):
        return 0, "ok"
    monkeypatch.setattr(
        "poor_code.domain.harness.nodes.execution.run_shell", fake_run_shell)
    state = _accept_runner_state(prior_check_results=(("A", True),))
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(state))
    assert r.output.passed is True
    assert r.branch == "pass"


@pytest.mark.asyncio
async def test_validation_runner_fails_on_regression(monkeypatch, tmp_path):
    async def fake_run_shell(command, cwd, cancel, *a, **k):
        return (1, "boom") if command == "cmd-a" else (0, "ok")
    monkeypatch.setattr(
        "poor_code.domain.harness.nodes.execution.run_shell", fake_run_shell)
    # A was green on the prior attempt; now it fails → regression.
    state = _accept_runner_state(prior_check_results=(("A", True),))
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(state))
    assert r.output.passed is False
    assert "A" in r.output.output and "regressed" in r.output.output
    assert r.branch == "fail"


@pytest.mark.asyncio
async def test_validation_runner_fails_when_zero_checks_green(monkeypatch, tmp_path):
    """Regression for the false-completion bug: with nothing yet green, the old
    no-regression-only rule passed at 0/N (there was nothing to regress), so
    completion_gate stamped 'done' on a wholly-broken task. Now 0/N green = fail."""
    async def fake_run_shell(command, cwd, cancel, *a, **k):
        return 1, "boom"  # every acceptance check fails → 0 green
    monkeypatch.setattr(
        "poor_code.domain.harness.nodes.execution.run_shell", fake_run_shell)
    state = _accept_runner_state()  # no prior green anywhere
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(state))
    assert r.output.passed is False
    assert r.branch == "fail"
    assert "no acceptance progress" in r.output.output


@pytest.mark.asyncio
async def test_validation_runner_fails_when_task_adds_no_new_green(monkeypatch, tmp_path):
    """A task that leaves the green set exactly where a sibling task already had it
    made no progress → not 'done' (even though nothing regressed)."""
    async def fake_run_shell(command, cwd, cancel, *a, **k):
        return (0, "ok") if command == "cmd-a" else (1, "boom")  # only A green
    monkeypatch.setattr(
        "poor_code.domain.harness.nodes.execution.run_shell", fake_run_shell)
    # t_prev already made A green; the active task t1 also only has A green → no gain.
    plan = Plan(tasks=(
        Task(id="t_prev", title="prev", purpose="p",
             attempts=(Attempt(id="p1", check_results=(("A", True),)),)),
        Task(id="t1", title="A", purpose="p", attempts=(Attempt(id="a2"),))))
    cur = Cursor(phase=Phase.IMPLEMENTING, current_node="validation_runner",
                 task_id="t1", attempt_id="a2")
    spec = AcceptanceSpec(checks=(
        AcceptanceCheck(criterion="A", command="cmd-a"),
        AcceptanceCheck(criterion="B", command="cmd-b")))
    state = SessionState(plan=plan, cursor=cur, acceptance=spec)
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(state))
    assert r.output.passed is False and r.branch == "fail"


@pytest.mark.asyncio
async def test_validation_runner_passes_when_task_adds_new_green(monkeypatch, tmp_path):
    """A task that newly turns a check green (no regression) is 'done', even though
    the full spec is not yet green — the rest is other tasks' / global_validator's job."""
    async def fake_run_shell(command, cwd, cancel, *a, **k):
        return (0, "ok") if command in ("cmd-a", "cmd-b") else (1, "x")  # A and B green
    monkeypatch.setattr(
        "poor_code.domain.harness.nodes.execution.run_shell", fake_run_shell)
    plan = Plan(tasks=(
        Task(id="t_prev", title="prev", purpose="p",
             attempts=(Attempt(id="p1", check_results=(("A", True),)),)),
        Task(id="t1", title="B", purpose="p", attempts=(Attempt(id="a2"),))))
    cur = Cursor(phase=Phase.IMPLEMENTING, current_node="validation_runner",
                 task_id="t1", attempt_id="a2")
    spec = AcceptanceSpec(checks=(
        AcceptanceCheck(criterion="A", command="cmd-a"),
        AcceptanceCheck(criterion="B", command="cmd-b"),
        AcceptanceCheck(criterion="C", command="cmd-c")))
    state = SessionState(plan=plan, cursor=cur, acceptance=spec)
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(state))
    assert r.output.passed is True and r.branch == "pass"


@pytest.mark.asyncio
async def test_validation_runner_falls_back_to_how_to_validate_without_acceptance(
        monkeypatch, tmp_path):
    seen = {}
    async def fake_run_shell(command, cwd, cancel, *a, **k):
        seen["command"] = command
        return 0, "ok"
    monkeypatch.setattr(
        "poor_code.domain.harness.nodes.execution.run_shell", fake_run_shell)
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p",
                            how_to_validate="pytest -q",
                            attempts=(Attempt(id="a1"),)),))
    cur = Cursor(phase=Phase.IMPLEMENTING, current_node="validation_runner",
                 task_id="t1", attempt_id="a1")
    state = SessionState(plan=plan, cursor=cur, acceptance=None)
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(state))
    assert seen["command"] == "pytest -q"
    assert r.output.passed is True and r.branch == "pass"


@pytest.mark.asyncio
async def test_validation_runner_records_check_results(monkeypatch, tmp_path):
    async def fake_run_shell(command, cwd, cancel, *a, **k):
        return (0, "ok") if command == "cmd-a" else (1, "boom")
    monkeypatch.setattr(
        "poor_code.domain.harness.nodes.execution.run_shell", fake_run_shell)
    state = _accept_runner_state()
    r = await ValidationRunner(cwd=tmp_path).run(_ctx(state))
    # the output records each check's result, and apply_to persists it onto the attempt
    assert r.output.check_results == (("A", True), ("B", False))
    new_state = r.output.apply_to(state)
    task = new_state.plan.tasks[0]
    active = next(a for a in task.attempts if a.id == "a2")
    assert active.check_results == (("A", True), ("B", False))


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
    # The task-execution loop is folded into the implement_loop subgraph; its inner
    # edges (task_selector/composer/implementer/.../completion_gate) live inside the
    # subgraph now, NOT in the outer FORWARD table. The outer table only carries the
    # entry into and exit out of the subgraph.
    assert FORWARD[("plan_gate", None)] == "plan_reviewer"
    assert FORWARD[("plan_reviewer", None)] == "plan_confirm_gate"
    assert FORWARD[("plan_confirm_gate", None)] == "provisioner"
    assert FORWARD[("provisioner", None)] == "implement_loop"
    assert FORWARD[("implement_loop", "done")] == "global_validator"
    assert FORWARD[("global_validator", "pass")] == "reporter"
    # the inner execution edges are no longer on the outer table
    for inner in (("task_selector", "task"), ("composer", None), ("implementer", None),
                  ("eng_gate", None), ("validator", None), ("validation_runner", "pass"),
                  ("validation_runner", "fail"), ("failure_analyst", None),
                  ("completion_gate", "done"), ("task_selector", "done")):
        assert inner not in FORWARD


def test_build_registry_has_code_nodes():
    from datetime import UTC, datetime
    from poor_code.domain.project_map.models import ProjectMap
    from poor_code.domain.harness import build_default_registry

    class _LLM:
        async def stream(self, messages, tools, response_format=None):
            if False:
                yield None

    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    reg = build_default_registry(llm=_LLM(), project_map=pm)
    # the code nodes now live INSIDE the implement_loop subgraph, not the outer registry
    loop = reg.get("implement_loop")
    assert loop is not None
    inner = loop._graph.nodes
    for n in ("task_selector", "eng_gate", "validation_runner", "completion_gate"):
        assert inner.get(n) is not None
        assert inner.get(n).name == n


@pytest.mark.asyncio
async def test_run_shell_returns_exit_code_and_output(tmp_path):
    from poor_code.domain.harness.nodes.execution import run_shell
    import asyncio as _a
    code, out = await run_shell("echo hello", tmp_path, _a.Event())
    assert code == 0 and "hello" in out
    code, _ = await run_shell("exit 7", tmp_path, _a.Event())
    assert code == 7


@pytest.mark.asyncio
async def test_eng_gate_repairs_below_cap_then_escalates_at_cap():
    from poor_code.domain.harness.node import NodeContext
    from poor_code.domain.harness.nodes.execution import EngGate
    from poor_code.domain.harness.nodes.validator import MAX_ADVERSARIAL_ROUNDS
    from poor_code.domain.session.models import (
        SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
        Attempt, VerdictKind, Layer)
    import asyncio as _a

    def _state(rounds):
        # attempt with NO patch → structurally invalid → eng_gate wants repair
        att = Attempt(id="t1-a1", patch=None, adversarial_rounds=rounds)
        return SessionState(
            plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                                  edit_scope=EditScope(editable=("a.txt",)),
                                  how_to_validate="true", status=TaskStatus.ACTIVE,
                                  attempts=(att,)),)),
            cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="eng_gate",
                          task_id="t1", attempt_id="t1-a1"))

    # below cap → repair (implementation)
    res = await EngGate().run(NodeContext(state=_state(0), cancel=_a.Event()))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.IMPLEMENTATION

    # at cap → escalate (terminates the eng_gate↔implementer loop)
    res = await EngGate().run(NodeContext(state=_state(MAX_ADVERSARIAL_ROUNDS), cancel=_a.Event()))
    assert res.verdict.kind is VerdictKind.ESCALATE
