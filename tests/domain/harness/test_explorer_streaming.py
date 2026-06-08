import asyncio
import pytest
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import Request, RequestKind, SessionState
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)
from pydantic import BaseModel


def _empty_map():
    return ProjectMap(version=2, generated_at=datetime.now(UTC),
                      cwd=Path("."), files=(), parse_errors=())


class _GrepArgs(BaseModel):
    pattern: str = ""


class _GrepStub:
    id = "grep"
    description = "stub"
    params = _GrepArgs
    async def execute(self, args, ctx):
        class R:
            output = "a.py:1: hit"
        return R()


class _ExploreThenEmitLLM:
    """Round 1: a grep tool call. Round 2 (extraction): emit_code_context."""
    def __init__(self):
        self.calls = 0
    async def stream(self, messages, tools, response_format=None):
        self.calls += 1
        if self.calls == 1:
            yield TextDelta(text="searching ")
            yield ToolCallStarted(call_id="g1", name="grep")
            yield ToolCallInputDelta(call_id="g1", json_delta='{"pattern":"x"}')
            yield ToolCallEnded(call_id="g1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield ToolCallStarted(call_id="e1", name="emit_code_context")
            yield ToolCallInputDelta(call_id="e1", json_delta='{"candidates":[]}')
            yield ToolCallEnded(call_id="e1")
            yield FinishedReason(reason="tool_calls")


class _Sink:
    def __init__(self):
        self.events = []
    def text_delta(self, t): self.events.append(("text", t))
    def node_thinking_delta(self, node, t): self.events.append(("thinking", t))
    def node_context(self, node, phase, messages): pass
    def node_raw_output(self, node, raw): pass
    def tool_started(self, cid, name, args): self.events.append(("start", name))
    def tool_finished(self, cid, result): self.events.append(("done", result))
    def tool_failed(self, cid, error): self.events.append(("fail", error))


@pytest.mark.asyncio
async def test_explorer_emits_tool_events_but_not_text():
    """Tool events (start/done) must reach the sink; raw reasoning prose must NOT."""
    node = ExploringNode(_ExploreThenEmitLLM(), project_map=_empty_map(),
                         tools=ToolRegistry([_GrepStub()]))
    sink = _Sink()
    ctx = NodeContext(
        state=SessionState(request=Request(raw_text="find x", kind=RequestKind.ENGINEERING)),
        cancel=asyncio.Event(), sink=sink)
    await node.run(ctx)
    # Raw text deltas must NOT be forwarded to the UI sink
    assert all(kind != "text" for kind, _ in sink.events), \
        f"Unexpected text events in sink: {sink.events}"
    # Tool events MUST still be visible
    assert ("start", "grep") in sink.events
    assert ("done", "a.py:1: hit") in sink.events
