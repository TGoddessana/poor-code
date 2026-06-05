from poor_code.domain.session.models import (
    Request, RequestKind, CodeRef, CodeContext, GroundingStatus,
    Cursor, Phase, Transition, TriggerKind,
    Verdict, VerdictKind, Layer,
    Step, StepKind, Task,
    EnvReport, SessionState,
)


def test_env_report_defaults():
    er = EnvReport()
    assert er.ready is False
    assert er.test_command == "" and er.install_steps == () and er.notes == ""


def test_session_state_carries_env_report():
    er = EnvReport(ready=True, test_command="pytest -q",
                   install_steps=("pip install -e .[test]",), notes="ok")
    st = SessionState().with_env_report(er)
    assert st.env_report is er
    assert SessionState().env_report is None


def test_step_defaults_are_empty():
    s = Step(id="t1.s1", kind=StepKind.IMPL)
    assert s.file == "" and s.anchor == "" and s.body == ""
    assert s.run == "" and s.expected == ""


def test_task_carries_ordered_steps():
    steps = (
        Step(id="t1.s1", kind=StepKind.TEST, file="tests/x_test.py",
             body="def test_x():\n    assert f() == 1", run="pytest -q", expected="PASS"),
        Step(id="t1.s2", kind=StepKind.IMPL, file="x.py", body="def f():\n    return 1"),
    )
    t = Task(id="t1", title="x", purpose="p", steps=steps)
    assert t.steps[0].kind is StepKind.TEST
    assert t.steps[1].body == "def f():\n    return 1"
    assert Task(id="t2", title="y", purpose="p").steps == ()


def test_request_kind_roundtrip():
    r = Request(raw_text="add oauth login", kind=RequestKind.ENGINEERING)
    assert r.kind is RequestKind.ENGINEERING
    assert r.raw_text == "add oauth login"


def test_code_context_holds_coderefs():
    cc = CodeContext(
        candidates=(CodeRef(file="src/a.py", symbol="login", lineno=10),),
        confusers=(CodeRef(file="src/b.py"),),
        related_tests=(CodeRef(file="tests/test_a.py"),),
    )
    assert cc.candidates[0].symbol == "login"
    assert cc.confusers[0].symbol is None  # whole-file ref


def test_code_context_grounding_defaults_to_not_found():
    assert CodeContext().grounding is GroundingStatus.NOT_FOUND


def test_code_context_grounding_can_be_greenfield():
    cc = CodeContext(grounding=GroundingStatus.GREENFIELD)
    assert cc.grounding is GroundingStatus.GREENFIELD


def test_verdict_repair_carries_layer():
    v = Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint="missing task")
    assert v.kind is VerdictKind.REPAIR and v.layer is Layer.PLAN


def test_cursor_and_transition_are_frozen():
    import dataclasses
    cur = Cursor(phase=Phase.LOCATING, current_node="locator")
    tr = Transition(from_node="router", to_node="locator",
                    trigger=TriggerKind.FORWARD, reason="engineering", ts_iso="2026-05-31T00:00:00+00:00")
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        cur.current_node = "x"  # type: ignore[misc]
    assert tr.to_node == "locator"


def test_query_and_userresponse_and_requirement_construct():
    from poor_code.domain.session.models import (
        Query, QueryKind, UserResponse, AnsweredQuery, Requirement,
    )
    q = Query(id="q1", kind=QueryKind.CHOOSE, prompt="A or B?",
              options=("A", "B"), rationale="changes the file layout")
    assert q.kind is QueryKind.CHOOSE
    assert q.options == ("A", "B")
    assert q.context is None and q.resolves is None

    resp = UserResponse(query_id="q1", answer="A", chosen_option="A")
    aq = AnsweredQuery(query=q, response=resp)
    assert aq.query.id == "q1" and aq.response.answer == "A"

    req = Requirement(summary="add google login",
                      acceptance=("provider file added",))
    assert req.summary == "add google login"
    assert req.out_of_scope == () and req.open_questions == ()


def test_phase_has_interviewing():
    from poor_code.domain.session.models import Phase
    assert Phase.INTERVIEWING.value == "interviewing"


def test_with_requirement_and_pending_query():
    from poor_code.domain.session.models import (
        SessionState, Requirement, Query, QueryKind,
    )
    st = SessionState()
    assert st.requirement is None and st.pending_query is None and st.interview == ()

    st2 = st.with_requirement(Requirement(summary="x"))
    assert st2.requirement.summary == "x"

    q = Query(id="q1", kind=QueryKind.CLARIFY, prompt="why?")
    st3 = st.with_pending_query(q)
    assert st3.pending_query is q


def test_with_user_response_records_and_clears():
    from poor_code.domain.session.models import (
        SessionState, Query, QueryKind, UserResponse,
    )
    q = Query(id="q1", kind=QueryKind.CONFIRM, prompt="reuse auth_store?")
    st = SessionState().with_pending_query(q)
    st2 = st.with_user_response(UserResponse(query_id="q1", answer="yes"))
    assert st2.pending_query is None
    assert len(st2.interview) == 1
    assert st2.interview[0].query.id == "q1"
    assert st2.interview[0].response.answer == "yes"


def test_with_user_response_rejects_mismatched_id():
    import pytest
    from poor_code.domain.session.models import (
        SessionState, Query, QueryKind, UserResponse,
    )
    st = SessionState().with_pending_query(
        Query(id="q1", kind=QueryKind.CLARIFY, prompt="?"))
    with pytest.raises(ValueError):
        st.with_user_response(UserResponse(query_id="WRONG", answer="x"))


def test_plan_task_value_objects():
    from poor_code.domain.session.models import (
        Dependency,
        EditScope,
        Plan,
        Task,
        TaskStatus,
    )
    scope = EditScope(editable=("src/auth.py",), readonly=("tests/test_auth.py",))
    task = Task(
        id="t1",
        title="Update auth flow",
        purpose="Support provider login",
        description="Wire provider selection into login.",
        edit_scope=scope,
        how_to_validate="pytest tests/test_auth.py",
    )
    plan = Plan(tasks=(task,), deps=(Dependency(task_id="t1", depends_on="t0"),))

    assert task.status is TaskStatus.PENDING
    assert task.context is None
    assert task.attempts == ()
    assert plan.tasks[0].edit_scope.editable == ("src/auth.py",)


def test_session_state_with_plan_is_immutable():
    from poor_code.domain.session.models import Plan, SessionState, Task

    plan = Plan(tasks=(Task(id="t1", title="A", purpose="B"),))
    state = SessionState()
    next_state = state.with_plan(plan)

    assert state.plan is None
    assert next_state.plan == plan


def test_task_context_and_attempt_stubs_exist():
    from poor_code.domain.session.models import Attempt, AttemptStatus, TaskContext

    ctx = TaskContext()
    attempt = Attempt(id="a0")
    assert ctx.refs == ()
    assert attempt.status is AttemptStatus.ACTIVE


def test_phase_has_planning():
    from poor_code.domain.session.models import Phase

    assert Phase.PLANNING.value == "planning"
