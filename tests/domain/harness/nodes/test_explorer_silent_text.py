"""Explorer must NOT leak raw text deltas to the sink during its tool loop."""
import asyncio
from datetime import UTC, datetime
from pathlib import Path
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import Request, RequestKind, SessionState
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import FinishedReason, TextDelta


class _Sink:
    def __init__(self): self.text = []
    def node_thinking_delta(self, name, t): self.text.append(t)
    def tool_started(self, *a, **k): ...
    def tool_finished(self, *a, **k): ...
    def tool_failed(self, *a, **k): ...
    def node_context(self, *a, **k): ...
    def node_raw_output(self, *a, **k): ...


class _LLM:
    provider_name = "x"; model = "m"
    async def stream(self, messages, tools, response_format=None):
        yield TextDelta(text="Let me grep for the slash handler...")
        yield FinishedReason(reason="stop")


@pytest.mark.asyncio
async def test_explore_does_not_leak_text_to_sink():
    pmap = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(), parse_errors=())
    node = ExploringNode(_LLM(), pmap, ToolRegistry([]))
    sink = _Sink()
    state = SessionState(request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    ctx = NodeContext(state=state, cancel=asyncio.Event(), sink=sink)
    await node._explore(ctx)
    assert sink.text == []
