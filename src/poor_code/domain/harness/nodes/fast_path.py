# src/poor_code/domain/harness/nodes/fast_path.py
"""FastPathNode — the lightweight (non-engineering) leaf. TEMPORARY: it wraps the
legacy Agent CC-loop and forwards its events to the sink. The CC-style loop is
slated for removal; when the harness owns execution end-to-end this node goes away.

route() has no forward edge for 'fast_path', so the Driver parks (terminal) once
this node returns — one casual exchange per turn."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.messages import SendPrompt


class FastPathNode:
    name = "fast_path"

    def __init__(self, agent) -> None:
        self._agent = agent

    async def run(self, ctx: NodeContext) -> NodeResult:
        assert ctx.state.request is not None, "FastPathNode requires state.request"
        cmd = SendPrompt(ctx.state.request.raw_text)
        async for event in self._agent.run(cmd, ctx.cancel):
            if ctx.sink is not None:
                ctx.sink.forward(event)
        return NodeResult(output=None)
