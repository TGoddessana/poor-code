import asyncio
import json
import uuid
import pytest
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness import build_default_registry, Driver, route
from poor_code.domain.session.models import SessionState, Cursor, Phase, Request, RequestKind
from poor_code.domain.session.store import SessionStore
from poor_code.domain.project_map.models import ProjectMap, FileEntry, Symbol, SymbolKind
from poor_code.provider.events import (
    TextDelta, ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class FakeLLMClient:
    """Routes canned structured output by which tool the node offered, so the
    same client drives Router (classify_request), Locator (emit_code_context),
    and Interviewer (interview_step) along their real agent paths. The
    interviewer step defaults to one 'ask' so the graph suspends there."""
    def __init__(self, *, code_context, kind="engineering"):
        self._by_tool = {
            "classify_request": {"kind": kind, "reason": "test"},
            "emit_code_context": code_context,
            "interview_step": {"action": "ask",
                               "query": {"kind": "clarify", "prompt": "scope?",
                                         "rationale": "scope is ambiguous"}},
        }

    async def stream(self, messages, tools, response_format=None):
        name = tools[0]["function"]["name"]
        if name not in self._by_tool:
            # ExploringNode stage ① exploration round: stop without read/grep
            yield TextDelta(text="enough")
            yield FinishedReason(reason="stop")
            return
        args = json.dumps(self._by_tool[name])
        yield ToolCallStarted(call_id="c1", name=name)
        yield ToolCallInputDelta(call_id="c1", json_delta=args)
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _map():
    sym = Symbol(name="login", kind=SymbolKind.FUNCTION, lineno=10,
                 signature=None, doc=None, calls=(), called_by=())
    fe = FileEntry(path="src/auth.py", language="python", content_hash="h",
                   symbols=(sym,), imports=(), imported_by=(), tests=())
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(fe,), parse_errors=())


@pytest.mark.asyncio
async def test_engineering_request_flows_to_code_context_and_checkpoints(tmp_path: Path):
    llm = FakeLLMClient(code_context={"candidates": [{"file": "src/auth.py", "symbol": "login"}],
                                      "confusers": [], "related_tests": []})
    registry = build_default_registry(llm=llm, project_map=_map())

    store = SessionStore(tmp_path)
    sid = uuid.uuid4().hex
    driver = Driver(registry, route, on_step=lambda s: store.write_session_state(sid, s))

    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="fix the login bug", kind=RequestKind.ENGINEERING),
    )
    final = await driver.run(start, asyncio.Event())

    # graph reached the interviewer and suspended on a question, with understanding produced
    assert final.cursor.current_node == "interviewer"
    assert final.pending_query is not None
    assert final.understanding.candidates[0].symbol == "login"

    # persisted: reloading the suspend checkpoint yields the same understanding + pending query
    reloaded = store.read_session_state(sid)
    assert reloaded.understanding.candidates[0].file == "src/auth.py"
    assert reloaded.cursor.current_node == "interviewer"
    assert reloaded.pending_query is not None


@pytest.mark.asyncio
async def test_empty_candidates_bounce_back_to_explorer_then_escalate(tmp_path: Path):
    # Explorer finds nothing → UnderstandingGate fires the first real back-edge.
    llm = FakeLLMClient(code_context={"candidates": [], "confusers": [], "related_tests": []})
    registry = build_default_registry(llm=llm, project_map=_map())

    visited: list[str] = []
    driver = Driver(registry, route, on_step=lambda s: visited.append(s.cursor.current_node))
    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="add a thing", kind=RequestKind.ENGINEERING),
    )
    final = await driver.run(start, asyncio.Event())

    # The cursor looped back to the explorer (the back-edge actually fired) ...
    assert visited.count("explorer") == 2
    # ... and, still empty on the retry, the gate escalated to the user.
    assert final.cursor.current_node == "user"


@pytest.mark.asyncio
async def test_lightweight_request_parks_at_fast_path(tmp_path: Path):
    registry = build_default_registry(
        llm=FakeLLMClient(kind="lightweight",
                          code_context={"candidates": [], "confusers": [], "related_tests": []}),
        project_map=_map())
    driver = Driver(registry, route)
    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="반갑다 너는 누구냐", kind=RequestKind.ENGINEERING),  # Router reclassifies
    )
    final = await driver.run(start, asyncio.Event())
    assert final.cursor.current_node == "fast_path"   # handed off to legacy agent.py path
    assert final.understanding is None                 # never reached locator


class ScriptedLLM:
    """Routes by tool name; interview_step pops a scripted step per call."""
    def __init__(self, *, kind, code_context, interview_steps, plan, acceptance=None):
        self._kind = kind
        self._cc = code_context
        self._steps = list(interview_steps)
        self._plan = plan
        self._acceptance = acceptance or {
            "checks": [{"criterion": "auth", "command": "pytest tests/test_auth.py"}]}

    async def stream(self, messages, tools, response_format=None):
        name = tools[0]["function"]["name"]
        if name == "classify_request":
            args = {"kind": self._kind, "reason": "t"}
        elif name == "emit_code_context":
            args = self._cc
        elif name == "interview_step":
            args = self._steps.pop(0)
        elif name == "emit_acceptance":
            args = self._acceptance
        elif name == "emit_critique":
            args = {"adequate": True, "counterexample": None}
        elif name == "emit_plan":
            args = self._plan
        else:
            # ExploringNode stage ① exploration round: stop without read/grep
            yield TextDelta(text="enough")
            yield FinishedReason(reason="stop")
            return
        payload = json.dumps(args)
        yield ToolCallStarted(call_id="c1", name=name)
        yield ToolCallInputDelta(call_id="c1", json_delta=payload)
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _planning_registry(llm, pm):
    from poor_code.domain.harness.registry import NodeRegistry
    from poor_code.domain.harness.nodes.router import Router
    from poor_code.domain.harness.nodes.explorer import ExploringNode
    from poor_code.domain.harness.nodes.gates import (
        AcceptanceGate, UnderstandingGate, PlanGate)
    from poor_code.domain.harness.nodes.acceptance_oracle import AcceptanceOracle
    from poor_code.domain.harness.nodes.acceptance_critic import AcceptanceCritic
    from poor_code.domain.harness.nodes.interviewer import Interviewer
    from poor_code.domain.harness.nodes.planner import Planner
    from poor_code.domain.harness.nodes.execution import TaskSelector
    from poor_code.domain.tool.registry import ToolRegistry
    from poor_code.domain.tool.read import ReadTool
    from poor_code.domain.tool.grep import GrepTool
    reg = NodeRegistry()
    reg.register(Router(llm))
    reg.register(ExploringNode(llm, project_map=pm, tools=ToolRegistry([ReadTool(), GrepTool()])))
    reg.register(UnderstandingGate())
    reg.register(Interviewer(llm, project_map=pm))
    reg.register(AcceptanceOracle(llm))
    reg.register(AcceptanceGate())
    reg.register(AcceptanceCritic(llm))
    reg.register(Planner(llm, project_map=pm))
    reg.register(PlanGate())
    reg.register(TaskSelector())
    return reg  # task_selector → composer (unregistered) → park


@pytest.mark.asyncio
async def test_interview_done_flows_through_planner_then_task_selector_advances_to_composer(tmp_path: Path):
    from poor_code.domain.session.models import UserResponse
    llm = ScriptedLLM(
        kind="engineering",
        code_context={"candidates": [{"file": "src/auth.py", "symbol": "login"}],
                      "confusers": [], "related_tests": []},
        interview_steps=[
            {"action": "ask", "query": {"kind": "choose", "prompt": "new file or extend?",
                                        "options": ["new", "extend"], "rationale": "layout"}},
            {"action": "ask", "query": {"kind": "confirm", "prompt": "reuse auth_store?",
                                        "rationale": "storage"}},
            {"action": "done", "requirement": {"summary": "add google login",
                                                "acceptance": ["providers/google.py"]}},
        ],
        plan={
            "tasks": [
                {
                    "title": "Add Google provider",
                    "purpose": "Support google login",
                    "edit_scope": {"editable": ["src/provider/google.py"]},
                    "how_to_validate": "pytest tests/test_auth.py",
                },
            ],
            "deps": [],
        },
    )
    registry = _planning_registry(llm, _map())
    driver = Driver(registry, route)
    state = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="add google login", kind=RequestKind.ENGINEERING),
    )

    questions_asked = 0
    while True:
        state = await driver.run(state, asyncio.Event())
        if state.pending_query is None:
            break
        questions_asked += 1
        q = state.pending_query
        state = state.with_user_response(
            UserResponse(query_id=q.id, answer="new",
                         chosen_option=(q.options[0] if q.options else None)))

    assert questions_asked == 2
    assert state.requirement is not None
    assert state.requirement.summary == "add google login"
    assert state.plan is not None
    assert state.plan.tasks[0].id == "t1"
    assert state.plan.tasks[0].edit_scope.editable == ("src/provider/google.py",)
    assert len(state.interview) == 2
    assert state.cursor.current_node == "composer"   # parked after task_selector (Plan 2: now IMPLEMENTING)
    assert state.cursor.phase is Phase.IMPLEMENTING


@pytest.mark.asyncio
async def test_with_user_response_guards_mismatched_query_id():
    from poor_code.domain.session.models import Query, QueryKind, UserResponse
    st = SessionState().with_pending_query(
        Query(id="q1", kind=QueryKind.CLARIFY, prompt="?"))
    with pytest.raises(ValueError):
        st.with_user_response(UserResponse(query_id="nope", answer="x"))


from poor_code.domain.harness.route import FORWARD, _SHALLOWEST
from poor_code.domain.session.models import Layer


def test_router_engineering_goes_to_explorer():
    assert FORWARD[("router", "engineering")] == "explorer"
    assert FORWARD[("explorer", None)] == "understanding_gate"
    assert _SHALLOWEST[Layer.UNDERSTANDING] == "explorer"
