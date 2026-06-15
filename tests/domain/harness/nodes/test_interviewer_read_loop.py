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
