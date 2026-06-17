import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.interviewer import Interviewer
from poor_code.domain.project_map.models import ProjectMap, FileEntry, Symbol, SymbolKind
from poor_code.domain.session.models import (
    SessionState, Request, RequestKind, CodeContext, CodeRef, Requirement,
)
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    TextDelta, ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)
from pydantic import BaseModel


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


class _ReadArgs(BaseModel):
    path: str = ""


class _ReadStub:
    id = "read"
    description = "stub read"
    params = _ReadArgs
    def __init__(self): self.calls = []
    async def execute(self, args, ctx):
        self.calls.append(args.path)
        class R:
            output = "   1\tdef on_input_changed(self, event): ...\n   2\t# submit wired via on_key"
        return R()


def test_interviewer_accepts_optional_tools():
    reg = ToolRegistry([_ReadStub()])
    node = Interviewer(_DummyLLM(), project_map=_map(), tools=reg)
    assert node._tools is reg


class _DummyLLM:
    async def stream(self, messages, tools, response_format=None):
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta='{"action":"done","requirement":{"summary":"x"}}')
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


class _ReadThenDecideLLM:
    """Unified loop: interview_step is offered alongside the working tools every round.
    Round 1: read to ground (the model chooses to read though it COULD decide).
    Round 2: emit interview_step done — its messages must carry round 1's read result."""
    def __init__(self): self.round = 0; self.decision_messages = None
    async def stream(self, messages, tools, response_format=None):
        self.round += 1
        if self.round == 1:                          # ground first
            yield ToolCallStarted(call_id="r1", name="read")
            yield ToolCallInputDelta(call_id="r1", json_delta='{"path":"src/auth.py"}')
            yield ToolCallEnded(call_id="r1")
            yield FinishedReason(reason="tool_calls")
        else:                                        # decide
            self.decision_messages = messages        # capture to prove transcript wiring
            yield ToolCallStarted(call_id="d1", name="interview_step")
            yield ToolCallInputDelta(call_id="d1",
                json_delta='{"action":"done","requirement":{"summary":"grounded by read"}}')
            yield ToolCallEnded(call_id="d1")
            yield FinishedReason(reason="tool_calls")


class _Sink:
    def __init__(self): self.tools = []
    def node_context(self, n, p, m): pass
    def node_raw_output(self, n, r): pass
    def node_thinking_delta(self, n, t): pass
    def tool_started(self, cid, name, args): self.tools.append(name)
    def tool_finished(self, cid, result): pass
    def tool_failed(self, cid, err): pass


class _GrepStub:
    id = "grep"
    description = "stub grep"
    params = _ReadArgs   # args are ignored by the stub; extra fields tolerated
    def __init__(self): self.calls = 0
    async def execute(self, args, ctx):
        self.calls += 1
        class R:
            output = "   1\tmax-height: 10;\n"
        return R()


class _GrepThenDecideUnifiedLLM:
    """Unified-loop expectation: working tools AND interview_step are offered in the
    SAME tool set every round. The model greps once, then emits interview_step done in
    a later round of the same loop. Under the old two-phase design grep and
    interview_step were never offered together, so a model still wanting to grep at the
    decision dispatch produced an invalid step and ESCALATED ('node user not registered')."""
    def __init__(self):
        self.offered: list[set] = []
        self.grepped = False
    async def stream(self, messages, tools, response_format=None):
        names = {t["function"]["name"] for t in tools}
        self.offered.append(names)
        if not self.grepped and "grep" in names:
            self.grepped = True
            yield ToolCallStarted(call_id="g1", name="grep")
            yield ToolCallInputDelta(call_id="g1",
                json_delta='{"pattern":"max-height","path_glob":"src/**/*.tcss"}')
            yield ToolCallEnded(call_id="g1")
            yield FinishedReason(reason="tool_calls")
            return
        decide = "interview_step" if "interview_step" in names else next(iter(names))
        yield ToolCallStarted(call_id="d1", name=decide)
        yield ToolCallInputDelta(call_id="d1",
            json_delta='{"action":"done","requirement":{"summary":"grounded by grep"}}')
        yield ToolCallEnded(call_id="d1")
        yield FinishedReason(reason="tool_calls")


@pytest.mark.asyncio
async def test_interviewer_unified_loop_executes_tool_then_decides():
    grep = _GrepStub()
    llm = _GrepThenDecideUnifiedLLM()
    node = Interviewer(llm, project_map=_map(), tools=ToolRegistry([grep]))
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event(), sink=_Sink()))
    # the grep was executed exactly once and the loop terminated on interview_step —
    # NOT escalated, NOT re-rolled into oblivion.
    assert grep.calls == 1
    assert isinstance(res.output, Requirement)
    assert res.output.summary == "grounded by grep"
    # the unified contract: working tools and the terminal interview_step live in ONE
    # tool set offered to the model every round.
    assert any({"grep", "interview_step"} <= r for r in llm.offered)


@pytest.mark.asyncio
async def test_interviewer_reads_files_before_deciding():
    read = _ReadStub()
    llm = _ReadThenDecideLLM()
    node = Interviewer(llm, project_map=_map(), tools=ToolRegistry([read]))
    sink = _Sink()
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event(), sink=sink))
    assert read.calls == ["src/auth.py"]          # the file was actually read
    assert "read" in sink.tools                    # surfaced through the sink
    assert isinstance(res.output, Requirement)
    assert res.output.summary == "grounded by read"
    # the read result is actually WIRED into the decision dispatch (not just sequenced)
    tool_msgs = [m for m in llm.decision_messages if m.get("role") == "tool"]
    assert any("on_input_changed" in m["content"] for m in tool_msgs)


@pytest.mark.asyncio
async def test_interviewer_without_tools_skips_read_loop():
    # tools=None -> no read loop; single decision dispatch (original behavior).
    node = Interviewer(_DummyLLM(), project_map=_map())   # no tools
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert isinstance(res.output, Requirement)


def test_interviewer_system_prompt_forbids_asking_code_checkable_facts():
    node = Interviewer(_DummyLLM(), project_map=_map(),
                       tools=ToolRegistry([_ReadStub()]))
    system = node.build_messages(_state())[0]["content"]
    assert "read/grep" in system
    # 코드로 확인 가능한 사실은 사용자에게 묻지 말라는 규율이 명시돼야 함
    assert "do NOT ask the user" in system


@pytest.mark.asyncio
async def test_interviewer_engine_path_still_asks_query():
    # ask 분기가 _terminal 경유 후에도 NodeResult.query를 내는지 (회귀 가드)
    class _AskLLM:
        async def stream(self, messages, tools, response_format=None):
            yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
            yield ToolCallInputDelta(call_id="c1", json_delta=json.dumps(
                {"action": "ask",
                 "query": {"kind": "clarify", "prompt": "p?", "rationale": "r"}}))
            yield ToolCallEnded(call_id="c1")
            yield FinishedReason(reason="tool_calls")
    node = Interviewer(_AskLLM(), project_map=_map())   # tools=None → no read loop
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.output is None
    assert res.query is not None and res.query.id == "q1"
