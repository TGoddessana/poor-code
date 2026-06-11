import uuid
from pathlib import Path
from poor_code.domain.session.store import SessionStore
from poor_code.domain.session.models import (
    SessionState, SessionStatus, Cursor, Phase, Request, RequestKind,
    CodeContext, CodeRef, Transition, TriggerKind,
)


def test_session_state_roundtrip_with_harness_fields(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = uuid.uuid4().hex
    st = SessionState(
        status=SessionStatus.BUSY,
        cursor=Cursor(phase=Phase.LOCATING, current_node="locator"),
        request=Request(raw_text="fix login", kind=RequestKind.ENGINEERING),
        understanding=CodeContext(candidates=(CodeRef(file="a.py", symbol="x", lineno=3),)),
        history=(Transition(from_node="router", to_node="locator",
                            trigger=TriggerKind.FORWARD, reason="engineering",
                            ts_iso="2026-05-31T00:00:00+00:00"),),
    )
    store.write_session_state(sid, st)
    got = store.read_session_state(sid)

    assert got.status is SessionStatus.BUSY
    assert got.cursor.current_node == "locator" and got.cursor.phase is Phase.LOCATING
    assert got.request.kind is RequestKind.ENGINEERING
    assert got.understanding.candidates[0].symbol == "x"
    assert got.history[0].to_node == "locator"


def test_empty_session_state_roundtrip(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = uuid.uuid4().hex
    store.write_session_state(sid, SessionState())
    got = store.read_session_state(sid)
    assert got.cursor is None and got.request is None and got.history == ()


def test_round_trip_pending_query_requirement_interview(tmp_path):
    from poor_code.domain.session.store import SessionStore
    from poor_code.domain.session.models import (
        SessionState, Query, QueryKind, UserResponse, Requirement, AnsweredQuery,
    )
    answered = AnsweredQuery(
        query=Query(id="q1", kind=QueryKind.CHOOSE, prompt="new file vs extend?",
                    options=("new", "extend")),
        response=UserResponse(query_id="q1", answer="new", chosen_option="new"),
    )
    st = SessionState(
        requirement=Requirement(summary="add google login",
                                acceptance=("provider file",),
                                open_questions=("scopes?",)),
        pending_query=Query(id="q2", kind=QueryKind.CONFIRM,
                            prompt="reuse auth_store?", rationale="storage choice"),
        interview=(answered,),
    )

    store = SessionStore(tmp_path)
    sid = "sess1"
    store.write_session_state(sid, st)
    back = store.read_session_state(sid)

    assert back.requirement.summary == "add google login"
    assert back.requirement.open_questions == ("scopes?",)
    assert back.pending_query.id == "q2"
    assert back.pending_query.kind is QueryKind.CONFIRM
    assert len(back.interview) == 1
    assert back.interview[0].query.options == ("new", "extend")
    assert back.interview[0].response.chosen_option == "new"


def test_round_trip_plan(tmp_path):
    from poor_code.domain.session.models import (
        Dependency,
        EditScope,
        FileSlot,
        Plan,
        SessionState,
        Step,
        StepKind,
        Task,
    )

    plan = Plan(
        tasks=(
            Task(
                id="t1",
                title="Add provider file",
                purpose="Implement Google auth provider",
                description="Create provider module.",
                edit_scope=EditScope(
                    editable=("src/poor_code/provider/providers/google.py",),
                    readonly=("src/poor_code/provider/providers/ollama_cloud.py",),
                    forbidden=("src/poor_code/messages.py",),
                ),
                how_to_validate="pytest tests/provider/test_google.py",
                steps=(Step(id="s1", kind=StepKind.IMPL, file="src/x.py", body="pass"),),
            ),
        ),
        deps=(Dependency(task_id="t1", depends_on="t0"),),
        file_plan=(FileSlot(path="src/x.py", responsibility="auth"),),
        plan_md="## t1\nDo the thing",
    )
    store = SessionStore(tmp_path)
    store.write_session_state("sid1", SessionState(plan=plan))
    back = store.read_session_state("sid1")

    assert back.plan == plan
    assert back.plan.tasks[0].edit_scope.forbidden == ("src/poor_code/messages.py",)
    assert back.plan.plan_md == "## t1\nDo the thing"
    assert back.plan.tasks[0].steps[0].kind is StepKind.IMPL


def test_round_trip_driver_control(tmp_path):
    from poor_code.domain.session.models import (
        Cursor,
        DriverControl,
        DriverDecisionRecord,
        NodeFeedbackPacket,
        Phase,
        SessionState,
        SubgraphCursor,
    )

    state = SessionState(
        driver_control=DriverControl(
            processed_steering_count=1,
            feedback_packets=(NodeFeedbackPacket(
                target_nodes=("implementer",),
                summary="tests edited",
                evidence=("diff touched tests/test_auth.py",),
                instruction="Edit src/auth.py only.",
                ttl_steps=2,
                source_steering_index=1,
            ),),
            subgraph_cursors=(SubgraphCursor(
                graph_name="implement_loop",
                cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="validator",
                              task_id="t1", attempt_id="a1"),
            ),),
            last_decision=DriverDecisionRecord(
                action="restart_current",
                target_node="implementer",
                reason="user corrected implementation",
            ),
        )
    )

    store = SessionStore(tmp_path)
    store.write_session_state("sid1", state)
    back = store.read_session_state("sid1")

    assert back.driver_control.processed_steering_count == 1
    assert back.driver_control.feedback_packets[0].instruction == "Edit src/auth.py only."
    assert back.subgraph_cursor("implement_loop").current_node == "validator"
    assert back.driver_control.last_decision.action == "restart_current"
