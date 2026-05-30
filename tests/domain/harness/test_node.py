import asyncio
import pytest
from poor_code.domain.harness.node import Node, NodeResult, NodeContext
from poor_code.domain.session.models import SessionState, CodeContext


class _Echo:
    name = "echo"
    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=CodeContext())


def test_noderesult_defaults():
    r = NodeResult(output=None)
    assert r.output is None and r.verdict is None


@pytest.mark.asyncio
async def test_node_protocol_runs():
    node = _Echo()
    assert isinstance(node, Node)
    ctx = NodeContext(state=SessionState(), cancel=asyncio.Event())
    result = await node.run(ctx)
    assert isinstance(result.output, CodeContext)
