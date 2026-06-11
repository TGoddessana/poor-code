import asyncio
from dataclasses import replace

from poor_code.domain.harness.driver import Driver, DriverRuntime
from poor_code.domain.harness.graph import EdgeTable, Graph
from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.smart_driver import (
    AdvisorDecision,
    AdviceRequest,
    SmartDriverAdvisor,
)
from poor_code.domain.harness.steering import driver_feedback_message
from poor_code.domain.session.models import (
    Cursor,
    DriverControl,
    DriverDecisionRecord,
    EditScope,
    Layer,
    NodeFeedbackPacket,
    Phase,
    Plan,
    Query,
    QueryKind,
    SessionState,
    SubgraphCursor,
    Task,
)


class _Node:
    phase = Phase.IMPLEMENTING

    def __init__(self, name: str, seen: list[str] | None = None) -> None:
        self.name = name
        self.seen = seen
        self.states: list[SessionState] = []

    async def run(self, ctx: NodeContext) -> NodeResult:
        if self.seen is not None:
            self.seen.append(self.name)
        self.states.append(ctx.state)
        return NodeResult()


class _Advisor:
    def __init__(self, decision: AdvisorDecision) -> None:
        self.decision = decision
        self.calls: list[AdviceRequest] = []

    async def advise(self, req: AdviceRequest) -> AdvisorDecision:
        self.calls.append(req)
        return self.decision


class _Sink:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def node_entered(self, node, phase, *, state=None, activity=""):
        self.events.append(("entered", node, phase, activity))

    def node_produced(self, node, phase, *, result=None, headline="", detail=()):
        self.events.append(("produced", node, phase, headline, detail))

    def node_finished(self, node, phase, duration_sec, status):
        self.events.append(("finished", node, phase, status))


def _state(node: str = "implementer") -> SessionState:
    return SessionState(
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node=node, task_id="t1"),
        steering_notes=("what are you doing?",),
        plan=Plan(tasks=(Task(
            id="t1",
            title="fix auth",
            purpose="",
            edit_scope=EditScope(editable=("src/auth.py",)),
        ),)),
    )


async def _run(driver: Driver, state: SessionState, sink=None) -> SessionState:
    return await driver.run(state, asyncio.Event(), sink=sink)


def test_smart_driver_disabled_does_not_call_advisor():
    reg = NodeRegistry()
    node = _Node("implementer")
    reg.register(node)
    advisor = _Advisor(AdvisorDecision(action="answer_only", user_message="paused"))
    runtime = DriverRuntime(advisor=advisor, smart_enabled=False)

    final = asyncio.run(_run(Driver(reg, lambda *_: None, runtime=runtime), _state()))

    assert advisor.calls == []
    assert node.states
    assert final.pending_query is None


def test_status_question_parks_with_smart_driver_query_and_intervention_card():
    reg = NodeRegistry()
    node = _Node("implementer")
    reg.register(node)
    advisor = _Advisor(AdvisorDecision(
        action="answer_only",
        reason="user asked status",
        user_message="현재 t1 구현 중입니다.",
        ask_prompt="현재 t1 구현 중입니다. 이어갈까요?",
    ))
    runtime = DriverRuntime(advisor=advisor, smart_enabled=True)
    sink = _Sink()

    final = asyncio.run(_run(Driver(reg, lambda *_: None, runtime=runtime), _state(), sink))

    assert final.pending_query is not None
    assert final.pending_query.kind is QueryKind.CONFIRM
    assert final.pending_query.resolves == "smart_driver_hitl"
    assert final.driver_control.processed_steering_count == 1
    assert node.states == []
    assert ("entered", "driver", "implementing", "Driver intervention") in sink.events
    assert any(ev[0] == "produced" and ev[1] == "driver" for ev in sink.events)


def test_restart_current_injects_feedback_once_then_consumes_it():
    reg = NodeRegistry()
    node = _Node("implementer")
    reg.register(node)
    packet = NodeFeedbackPacket(
        target_nodes=("implementer",),
        summary="tests were edited",
        evidence=("latest diff touched tests/test_auth.py",),
        instruction="Keep tests as oracle and edit src/auth.py only.",
    )
    advisor = _Advisor(AdvisorDecision(
        action="restart_current",
        reason="implementation feedback",
        user_message="구현자에게 테스트를 건드리지 말라고 지시할게요.",
        feedback_packets=(packet,),
    ))
    runtime = DriverRuntime(advisor=advisor, smart_enabled=True)

    final = asyncio.run(_run(Driver(reg, lambda *_: None, runtime=runtime), _state()))

    assert node.states
    msg = driver_feedback_message(node.states[0], "implementer")
    assert msg is not None
    assert "Keep tests as oracle" in msg["content"]
    assert final.driver_control.feedback_packets == ()


def test_pending_query_objection_is_briefed_then_cleared_for_restart():
    reg = NodeRegistry()
    node = _Node("interviewer")
    reg.register(node)
    pending = Query(
        id="q1",
        kind=QueryKind.CLARIFY,
        prompt="Which footer style do you want?",
        options=("bottom bar", "new line"),
        rationale="Need to decide UI placement.",
    )
    packet = NodeFeedbackPacket(
        target_nodes=("interviewer",),
        summary="pending question missed the user's intent",
        evidence=("User objected to q1 instead of answering it.",),
        instruction="Ask a replacement question about the actual UI constraint.",
    )
    advisor = _Advisor(AdvisorDecision(
        action="restart_current",
        reason="user objected to the pending query",
        user_message="인터뷰 질문을 다시 구성할게요.",
        feedback_packets=(packet,),
    ))
    runtime = DriverRuntime(advisor=advisor, smart_enabled=True)
    state = SessionState(
        cursor=Cursor(phase=Phase.INTERVIEWING, current_node="interviewer"),
        pending_query=pending,
        steering_notes=("이 질문이 아닌데?",),
    )

    final = asyncio.run(_run(Driver(reg, lambda *_: None, runtime=runtime), state))

    assert advisor.calls and advisor.calls[0].state.pending_query is pending
    assert node.states and node.states[0].pending_query is None
    msg = driver_feedback_message(node.states[0], "interviewer")
    assert msg is not None
    assert "replacement question" in msg["content"]
    assert final.pending_query is None


def test_smart_driver_briefing_includes_pending_query(tmp_path):
    pending = Query(
        id="q1",
        kind=QueryKind.CHOOSE,
        prompt="Which footer style do you want?",
        options=("bottom bar", "new line"),
        resolves="footer_style",
        rationale="Need to decide UI placement.",
    )
    state = SessionState(
        cursor=Cursor(phase=Phase.INTERVIEWING, current_node="interviewer"),
        pending_query=pending,
        steering_notes=("이 질문이 아닌데?",),
    )
    req = AdviceRequest(
        state=state,
        graph_name="root",
        current_node="interviewer",
        available_nodes=("explorer", "interviewer"),
        cwd=tmp_path,
    )

    briefing = SmartDriverAdvisor(llm=object(), cwd=tmp_path)._briefing(req)

    assert "PENDING QUERY:" in briefing
    assert "Which footer style do you want?" in briefing
    assert "bottom bar, new line" in briefing
    assert "이 질문이 아닌데?" in briefing


def test_bubble_repair_routes_to_planner_in_current_graph():
    seen: list[str] = []
    reg = NodeRegistry()
    reg.register(_Node("implement_loop", seen))
    reg.register(_Node("planner", seen))

    def route(node, result, state):
        if result.verdict is not None and result.verdict.layer is Layer.PLAN:
            return "planner"
        return None

    advisor = _Advisor(AdvisorDecision(
        action="bubble_repair",
        layer="plan",
        reason="task split is wrong",
        user_message="플래너로 되돌릴게요.",
    ))
    runtime = DriverRuntime(advisor=advisor, smart_enabled=True)
    state = _state("implement_loop")

    final = asyncio.run(_run(Driver(reg, route, runtime=runtime), state))

    assert seen == ["planner"]
    assert final.cursor is not None and final.cursor.current_node == "planner"
    assert final.repair_hint == "task split is wrong"


def test_compiled_graph_checkpoints_and_resumes_child_cursor():
    seen: list[str] = []
    reg = NodeRegistry()
    reg.register(_Node("a", seen))
    reg.register(_Node("b", seen))
    graph = Graph(
        nodes=reg,
        edges=EdgeTable(forward={("a", None): "b"}, back_edges={}),
        entry="a",
    )

    def fork(parent):
        return replace(
            parent.with_subgraph_cursor("loop", None),
            cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="a"),
        )

    def merge(parent, child):
        return replace(child, cursor=parent.cursor)

    compiled = graph.compile(name="loop", fork=fork, merge=merge, phase=Phase.IMPLEMENTING)
    checkpoints: list[SessionState] = []
    parent = SessionState(cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="loop"))
    runtime = DriverRuntime(on_step=checkpoints.append)

    asyncio.run(compiled.run(NodeContext(parent, asyncio.Event(), runtime=runtime)))

    assert any(
        st.subgraph_cursor("loop") is not None
        and st.subgraph_cursor("loop").current_node == "b"
        for st in checkpoints
    )

    seen.clear()
    saved = next(
        st for st in checkpoints
        if st.subgraph_cursor("loop") is not None
        and st.subgraph_cursor("loop").current_node == "b"
    )
    asyncio.run(compiled.run(NodeContext(saved, asyncio.Event(), runtime=runtime)))
    assert seen == ["b"]


def test_driver_control_roundtrip_shape_is_dataclass_friendly():
    state = SessionState(
        driver_control=DriverControl(
            processed_steering_count=2,
            feedback_packets=(NodeFeedbackPacket(
                target_nodes=("planner",),
                summary="bad split",
                evidence=("plan_md t2 too broad",),
                instruction="Split t2.",
            ),),
            subgraph_cursors=(SubgraphCursor(
                graph_name="implement_loop",
                cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer"),
            ),),
            last_decision=DriverDecisionRecord(action="redirect", target_node="planner"),
        )
    )

    assert state.driver_control.processed_steering_count == 2
    assert state.subgraph_cursor("implement_loop").current_node == "implementer"
