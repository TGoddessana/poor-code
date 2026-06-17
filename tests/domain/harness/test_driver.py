import asyncio
import pytest
from poor_code.domain.harness.driver import Driver, GLOBAL_STEP_BUDGET
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.node import NodeResult, NodeContext
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Request, RequestKind, CodeContext, CodeRef,
)


class _RouterStub:
    name = "router"
    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=Request(raw_text="add x", kind=RequestKind.ENGINEERING),
                          branch="engineering")


class _ExplorerStub:
    name = "explorer"
    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=CodeContext(candidates=(CodeRef(file="a.py", symbol="x"),)))


@pytest.mark.asyncio
async def test_driver_runs_router_then_explorer_then_parks():
    reg = NodeRegistry()
    reg.register(_RouterStub())
    reg.register(_ExplorerStub())  # no 'understanding_gate' registered → park there

    checkpoints: list[str] = []
    driver = Driver(reg, route, on_step=lambda s: checkpoints.append(s.cursor.current_node))

    start = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="router"))
    final = await driver.run(start, asyncio.Event())

    # parked at unregistered 'understanding_gate' after explorer produced understanding
    assert final.cursor.current_node == "understanding_gate"
    assert final.request is not None and final.request.kind is RequestKind.ENGINEERING
    assert final.understanding.candidates[0].symbol == "x"
    assert "explorer" in checkpoints


@pytest.mark.asyncio
async def test_driver_stops_when_route_returns_none():
    class _Terminal:
        name = "router"
        async def run(self, ctx): return NodeResult(output=Request(raw_text="?", kind=RequestKind.LIGHTWEIGHT), branch="lightweight")
    reg = NodeRegistry(); reg.register(_Terminal())
    driver = Driver(reg, route)
    start = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="router"))
    final = await driver.run(start, asyncio.Event())
    # router lightweight → 'fast_path' (unknown) → park
    assert final.cursor.current_node == "fast_path"


@pytest.mark.asyncio
async def test_driver_suspends_on_query_and_keeps_cursor():
    from poor_code.domain.harness.node import NodeResult, NodeContext
    from poor_code.domain.session.models import Query, QueryKind

    class _AskStub:
        name = "interviewer"
        async def run(self, ctx):
            return NodeResult(query=Query(id="q1", kind=QueryKind.CLARIFY, prompt="why?"))

    reg = NodeRegistry()
    reg.register(_AskStub())
    driver = Driver(reg, route)
    start = SessionState(cursor=Cursor(phase=Phase.INTERVIEWING, current_node="interviewer"),
                         request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    final = await driver.run(start, asyncio.Event())

    assert final.pending_query is not None
    assert final.pending_query.id == "q1"
    assert final.cursor.current_node == "interviewer"   # cursor stayed; re-entrant
    # suspend did not append a transition
    assert all(t.to_node != "interviewer" or t.from_node != "interviewer"
               for t in final.history)


@pytest.mark.asyncio
async def test_driver_applies_requirement_and_routes_to_spec_confirm_gate():
    from poor_code.domain.harness.node import NodeResult
    from poor_code.domain.session.models import Requirement

    class _DoneStub:
        name = "interviewer"
        async def run(self, ctx):
            return NodeResult(output=Requirement(summary="done"))

    reg = NodeRegistry()
    reg.register(_DoneStub())   # spec_confirm_gate unregistered → park
    driver = Driver(reg, route)
    start = SessionState(cursor=Cursor(phase=Phase.INTERVIEWING, current_node="interviewer"),
                         request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    final = await driver.run(start, asyncio.Event())

    assert final.requirement is not None and final.requirement.summary == "done"
    assert final.cursor.current_node == "spec_confirm_gate"   # forwarded, then parked


from poor_code.domain.session.models import Verdict, VerdictKind, Layer


import pytest
from poor_code.domain.session.models import (
    Plan, Task, Cursor, Phase, TaskStatus, AttemptStatus,
    SelectedTask, Attempt, ValidationResult, FeedbackEntry, TaskCompleted,
)


def _apply(state, output):
    # Driver._apply is a staticmethod; exercise it directly.
    return Driver._apply(state, NodeResult(output=output))


def _base():
    plan = Plan(tasks=(Task(id="t1", title="A", purpose="p"),))
    return SessionState(plan=plan,
                        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="x"))


def test_apply_selected_task():
    s = _apply(_base(), SelectedTask(task_id="t1"))
    assert s.cursor.task_id == "t1"
    assert [t for t in s.plan.tasks if t.id == "t1"][0].status is TaskStatus.ACTIVE


def test_apply_attempt_appends():
    s = _apply(_base().with_active_task("t1"), Attempt(id="a1"))
    assert s.plan.tasks[0].attempts[0].id == "a1"
    assert s.cursor.attempt_id == "a1"


def test_apply_validation_result_attaches():
    s = _apply(_base().with_active_task("t1").append_attempt("t1", Attempt(id="a1")),
               ValidationResult(command="true", exit_code=0, passed=True))
    assert s.plan.tasks[0].attempts[0].run_result.passed is True


def test_apply_feedback_entry():
    s = _apply(_base(), FeedbackEntry(failure_type="x", symptom="y", prevention_hint="z"))
    assert s.feedback.entries[0].failure_type == "x"


def test_apply_task_completed_marks_done():
    s0 = _base().with_active_task("t1").append_attempt("t1", Attempt(id="a1"))
    s = _apply(s0, TaskCompleted(task_id="t1", attempt_id="a1"))
    assert s.plan.tasks[0].status is TaskStatus.DONE
    assert s.plan.tasks[0].attempts[0].status is AttemptStatus.DONE


class _GateNode:
    """Stateful dummy: REPAIR on first visit, ADVANCE on the second so the loop
    terminates (ADVANCE -> FORWARD interviewer -> unregistered -> park)."""
    name = "understanding_gate"
    def __init__(self):
        self.calls = 0
    async def run(self, ctx):
        self.calls += 1
        if self.calls == 1:
            return NodeResult(output=None, verdict=Verdict(
                kind=VerdictKind.REPAIR, layer=Layer.UNDERSTANDING, hint="widen X"))
        return NodeResult(output=None, verdict=Verdict(kind=VerdictKind.ADVANCE))


class _Explorer:
    name = "explorer"
    def __init__(self):
        self.seen_hint = "UNSET"
    async def run(self, ctx):
        self.seen_hint = ctx.state.repair_hint           # hint reached the node
        return NodeResult(output=CodeContext(candidates=()))


def _fake_route(node, result, state):
    # isolate the Driver from route.py topology: REPAIR -> explorer,
    # explorer -> gate, gate ADVANCE -> stop (park).
    v = result.verdict
    if v is not None and v.kind is VerdictKind.REPAIR:
        return "explorer"
    if node == "explorer":
        return "understanding_gate"
    return None


@pytest.mark.asyncio
async def test_driver_sets_repair_hint_on_repair_then_clears_on_codecontext():
    explorer = _Explorer()
    reg = NodeRegistry()
    reg.register(_GateNode())
    reg.register(explorer)
    state = SessionState(
        understanding=CodeContext(candidates=()),
        cursor=Cursor(phase=Phase.LOCATING, current_node="understanding_gate"),
    )
    # gate(call1)->REPAIR sets repair_hint; route->explorer reads it; explorer's
    # CodeContext clears it; gate(call2)->ADVANCE-> stop (park).
    final = await Driver(reg, _fake_route).run(state, asyncio.Event())
    assert explorer.seen_hint == "widen X"               # hint carried to explorer
    assert final.repair_hint is None                     # cleared on CodeContext apply


@pytest.mark.asyncio
async def test_apply_task_context_and_upsert_attempt_and_clears_hint():
    from poor_code.domain.harness.driver import Driver
    from poor_code.domain.harness.node import NodeResult
    from poor_code.domain.session.models import (
        SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
        TaskContext, CodeRef, Attempt, ChangeRecord)
    st = SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("a.txt",)),
                              how_to_validate="test -f a.txt", status=TaskStatus.ACTIVE),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="composer", task_id="t1"),
        repair_hint="old hint")
    # TaskContext applied
    st = Driver._apply(st, NodeResult(output=TaskContext(refs=(CodeRef(file="a.txt"),))))
    assert st.plan.tasks[0].context.refs[0].file == "a.txt"
    # Attempt upserted AND repair_hint cleared
    st = Driver._apply(st, NodeResult(output=Attempt(id="t1-a1", patch=ChangeRecord(files=("a.txt",)))))
    assert len(st.plan.tasks[0].attempts) == 1
    assert st.repair_hint is None
    # same-id Attempt replaces in place
    st = Driver._apply(st, NodeResult(output=Attempt(id="t1-a1", adversarial_rounds=1)))
    assert len(st.plan.tasks[0].attempts) == 1
    assert st.plan.tasks[0].attempts[0].adversarial_rounds == 1


def test_apply_report_sets_state_report():
    from poor_code.domain.harness.driver import Driver
    from poor_code.domain.harness.node import NodeResult
    from poor_code.domain.session.models import Report, ReportOutcome, SessionState

    r = Report(outcome=ReportOutcome.SUCCEEDED, summary="ok")
    new = Driver._apply(SessionState(), NodeResult(output=r))
    assert new.report is r


def test_apply_delegates_to_output_apply_to():
    from poor_code.domain.session.models import EnvReport, SessionState
    er = EnvReport()
    new = Driver._apply(SessionState(), NodeResult(output=er))
    assert new.env_report is er


def test_apply_noop_when_output_none():
    from poor_code.domain.session.models import SessionState
    s = SessionState()
    assert Driver._apply(s, NodeResult(output=None)) is s


def test_unregistered_node_park_records_reason():
    reg = NodeRegistry()  # empty → target node is unregistered
    driver = Driver(reg, route=lambda *a, **k: None)
    state = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="fast_path"))
    out = asyncio.run(driver.run(state, asyncio.Event()))
    assert driver.last_escape is not None
    assert driver.last_escape.kind is VerdictKind.ESCALATE
    assert "fast_path" in (driver.last_escape.query or "")


class _SpinNode:
    name = "spin"
    phase = Phase.ROUTING
    async def run(self, ctx):
        return NodeResult()  # no output/verdict → keeps forwarding


def test_global_step_budget_aborts_runaway():
    reg = NodeRegistry(); reg.register(_SpinNode())
    driver = Driver(reg, route=lambda node, result, state: "spin")  # always loops back
    state = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="spin"))
    out = asyncio.run(driver.run(state, asyncio.Event()))
    assert driver.last_escape is not None
    assert driver.last_escape.kind is VerdictKind.ESCALATE
    assert str(GLOBAL_STEP_BUDGET) in (driver.last_escape.query or "")
