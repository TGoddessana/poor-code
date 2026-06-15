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
    """Round 1 (read loop): call read. Round 2: no tool call -> loop ends.
    Round 3 (decision dispatch): emit interview_step done."""
    def __init__(self): self.round = 0
    async def stream(self, messages, tools, response_format=None):
        self.round += 1
        names = [t["function"]["name"] for t in tools]
        if "interview_step" in names:               # decision dispatch
            yield ToolCallStarted(call_id="d1", name="interview_step")
            yield ToolCallInputDelta(call_id="d1",
                json_delta='{"action":"done","requirement":{"summary":"grounded by read"}}')
            yield ToolCallEnded(call_id="d1")
            yield FinishedReason(reason="tool_calls")
        elif self.round == 1:                        # read-loop round 1
            yield ToolCallStarted(call_id="r1", name="read")
            yield ToolCallInputDelta(call_id="r1", json_delta='{"path":"src/auth.py"}')
            yield ToolCallEnded(call_id="r1")
            yield FinishedReason(reason="tool_calls")
        else:                                        # read-loop round 2: stop
            yield TextDelta(text="enough context")
            yield FinishedReason(reason="stop")


class _Sink:
    def __init__(self): self.tools = []
    def node_context(self, n, p, m): pass
    def node_raw_output(self, n, r): pass
    def node_thinking_delta(self, n, t): pass
    def tool_started(self, cid, name, args): self.tools.append(name)
    def tool_finished(self, cid, result): pass
    def tool_failed(self, cid, err): pass


@pytest.mark.asyncio
async def test_interviewer_reads_files_before_deciding():
    read = _ReadStub()
    node = Interviewer(_ReadThenDecideLLM(), project_map=_map(),
                       tools=ToolRegistry([read]))
    sink = _Sink()
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event(), sink=sink))
    assert read.calls == ["src/auth.py"]          # the file was actually read
    assert "read" in sink.tools                    # surfaced through the sink
    assert isinstance(res.output, Requirement)
    assert res.output.summary == "grounded by read"


@pytest.mark.asyncio
async def test_interviewer_without_tools_skips_read_loop():
    # tools=None -> no read loop; single decision dispatch (original behavior).
    node = Interviewer(_DummyLLM(), project_map=_map())   # no tools
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert isinstance(res.output, Requirement)
