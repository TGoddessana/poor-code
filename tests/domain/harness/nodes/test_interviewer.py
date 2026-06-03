import asyncio
import json
import pytest
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness.node import NodeContext, StructuredOutputError
from poor_code.domain.harness.nodes.interviewer import Interviewer, MAX_ROUNDS
from poor_code.domain.session.models import (
    SessionState, Request, RequestKind, CodeContext, CodeRef, GroundingStatus,
    Query, QueryKind, UserResponse, AnsweredQuery, Requirement,
)
from poor_code.domain.project_map.models import ProjectMap, FileEntry, Symbol, SymbolKind
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class FakeLLMClient:
    def __init__(self, args_obj):
        self._args = json.dumps(args_obj)

    async def stream(self, messages, tools):
        assert len(tools) == 1
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=self._args)
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _map():
    sym = Symbol(name="login", kind=SymbolKind.FUNCTION, lineno=10,
                 signature="def login(user, pw) -> Session", doc=None, calls=(), called_by=())
    fe = FileEntry(path="src/auth.py", language="python", content_hash="h",
                   symbols=(sym,), imports=(), imported_by=(), tests=())
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(fe,), parse_errors=())


def _state(interview=()):
    return SessionState(
        request=Request(raw_text="add google login", kind=RequestKind.ENGINEERING),
        understanding=CodeContext(candidates=(CodeRef(file="src/auth.py", symbol="login"),)),
        interview=interview,
    )


@pytest.mark.asyncio
async def test_interviewer_asks_one_question():
    llm = FakeLLMClient({"action": "ask",
                         "query": {"kind": "choose", "prompt": "new file or extend auth?",
                                   "options": ["new", "extend"], "rationale": "file layout"}})
    node = Interviewer(llm, project_map=_map())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.output is None
    assert res.query is not None
    assert res.query.id == "q1"
    assert res.query.kind is QueryKind.CHOOSE
    assert res.query.options == ("new", "extend")


@pytest.mark.asyncio
async def test_interviewer_emits_requirement_when_done():
    llm = FakeLLMClient({"action": "done",
                         "requirement": {"summary": "add google social login",
                                         "acceptance": ["providers/google.py added",
                                                        "validated by tests/test_google.py"],
                                         "out_of_scope": ["other OAuth"]}})
    node = Interviewer(llm, project_map=_map())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.query is None
    assert isinstance(res.output, Requirement)
    assert res.output.summary == "add google social login"
    assert "providers/google.py added" in res.output.acceptance


@pytest.mark.asyncio
async def test_interviewer_question_id_increments_with_rounds():
    llm = FakeLLMClient({"action": "ask",
                         "query": {"kind": "clarify", "prompt": "next?", "rationale": "r"}})
    prior = (AnsweredQuery(
        query=Query(id="q1", kind=QueryKind.CLARIFY, prompt="?"),
        response=UserResponse(query_id="q1", answer="a")),)
    node = Interviewer(llm, project_map=_map())
    res = await node.run(NodeContext(state=_state(interview=prior), cancel=asyncio.Event()))
    assert res.query.id == "q2"


@pytest.mark.asyncio
async def test_interviewer_cap_forces_done_even_if_model_asks():
    # at cap (interview length == MAX_ROUNDS), action=ask is overridden to done.
    prior = tuple(
        AnsweredQuery(query=Query(id=f"q{i}", kind=QueryKind.CLARIFY, prompt="?"),
                      response=UserResponse(query_id=f"q{i}", answer="a"))
        for i in range(1, MAX_ROUNDS + 1)
    )
    llm = FakeLLMClient({"action": "ask",
                         "query": {"kind": "clarify", "prompt": "more?", "rationale": "r"},
                         "requirement": {"summary": "forced finalize",
                                         "open_questions": ["still unsure"]}})
    node = Interviewer(llm, project_map=_map())
    res = await node.run(NodeContext(state=_state(interview=prior), cancel=asyncio.Event()))
    assert res.query is None
    assert isinstance(res.output, Requirement)
    assert res.output.summary == "forced finalize"


@pytest.mark.asyncio
async def test_interviewer_schema_invalid_output_raises_with_raw_payload():
    # A model that violates the schema — here `query` as a bare string instead of
    # the object — is re-rolled, then (still bad) surfaces the FULL raw payload
    # (Pydantic's own message truncates it).
    bad_prompt = "'원격 제어'의 범위가 무엇입니까?"
    llm = FakeLLMClient({"action": "ask", "query": bad_prompt})
    node = Interviewer(llm, project_map=_map())
    with pytest.raises(StructuredOutputError) as exc:
        await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    err = exc.value
    assert err.node == "interviewer"
    assert "query" in err.detail                       # points at the bad field
    assert json.loads(err.raw)["query"] == bad_prompt  # full raw payload retained
    assert "raw payload" in str(err)                   # surfaced for the failed-turn UI


def _greenfield_state():
    return SessionState(
        request=Request(raw_text="create hello.txt", kind=RequestKind.ENGINEERING),
        understanding=CodeContext(candidates=(), grounding=GroundingStatus.GREENFIELD),
    )


def test_interviewer_context_flags_greenfield_mode():
    node = Interviewer(FakeLLMClient({"action": "done", "requirement": {"summary": "x"}}),
                       project_map=_map())
    user = node.build_messages(_greenfield_state())[-1]["content"]
    assert "MODE: greenfield" in user


def test_interviewer_context_no_greenfield_flag_when_grounded():
    node = Interviewer(FakeLLMClient({"action": "done", "requirement": {"summary": "x"}}),
                       project_map=_map())
    user = node.build_messages(_state())[-1]["content"]  # _state() has candidates, default grounding
    assert "MODE: greenfield" not in user


@pytest.mark.asyncio
async def test_interviewer_context_includes_signature_and_transcript():
    node = Interviewer(FakeLLMClient({"action": "done", "requirement": {"summary": "x"}}),
                       project_map=_map())
    prior = (AnsweredQuery(
        query=Query(id="q1", kind=QueryKind.CHOOSE, prompt="new or extend?"),
        response=UserResponse(query_id="q1", answer="new")),)
    msgs = node.build_messages(_state(interview=prior))
    user = msgs[-1]["content"]
    assert "def login(user, pw) -> Session" in user   # signature rendered
    assert "new or extend?" in user                    # transcript rendered
    assert "new" in user
