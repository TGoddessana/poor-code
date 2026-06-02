import asyncio
import pytest
from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.fast_path import FastPathNode
from poor_code.domain.session.models import Request, RequestKind, SessionState
from poor_code.messages import (
    AssistantTextDelta, TurnEnded, TurnStarted,
)


class _FakeAgent:
    """Stand-in for Agent.run — yields a turn envelope + content."""
    def __init__(self):
        self.llm = None
        self.seen_text = None
    async def run(self, cmd, cancel):
        self.seen_text = cmd.text
        yield TurnStarted(cmd_id="x", turn_id="AGENT")
        yield AssistantTextDelta(turn_id="AGENT", text="hello")
        yield TurnEnded(turn_id="AGENT", duration_sec=0.1, model="m")


class _Sink:
    def __init__(self):
        self.events = []
    def forward(self, ev):
        self.events.append(ev)


@pytest.mark.asyncio
async def test_fast_path_forwards_content_returns_terminal():
    agent = _FakeAgent()
    node = FastPathNode(agent)
    sink = _Sink()
    ctx = NodeContext(
        state=SessionState(request=Request(raw_text="hi", kind=RequestKind.LIGHTWEIGHT)),
        cancel=asyncio.Event(), sink=sink)
    result = await node.run(ctx)
    assert agent.seen_text == "hi"
    assert result.output is None and result.query is None
    # the sink received the forwarded events (filtering happens inside TurnSink.forward)
    assert any(isinstance(e, AssistantTextDelta) for e in sink.events)
