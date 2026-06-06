import asyncio
from dataclasses import replace
import pytest
from poor_code.domain.harness.graph import Graph, EdgeTable, CompiledGraph
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.node import NodeResult, NodeContext
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Requirement, Verdict, VerdictKind, Layer,
)


class _Producer:
    name = "inner_producer"
    phase = Phase.PLANNING
    async def run(self, ctx):
        return NodeResult(output=Requirement(summary="sub-done"))


def _sub_graph():
    reg = NodeRegistry(); reg.register(_Producer())
    edges = EdgeTable(forward={}, back_edges={})   # producer → forward miss → None → stop
    return Graph(nodes=reg, edges=edges, entry="inner_producer")


@pytest.mark.asyncio
async def test_compiled_graph_runs_inner_and_merges():
    seen = {}
    def fork(parent):
        return replace(parent, cursor=Cursor(phase=Phase.PLANNING, current_node="inner_producer"))
    def merge(parent, child):
        seen["child_req"] = child.requirement.summary
        return replace(parent, requirement=child.requirement)

    cg = CompiledGraph(_sub_graph(), name="sub", fork=fork, merge=merge)
    assert cg.name == "sub"
    parent = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="sub"))
    ctx = NodeContext(state=parent, cancel=asyncio.Event())
    result = await cg.run(ctx)
    assert result.verdict is None
    merged = result.output.apply_to(parent)     # _Merge.apply_to runs merge(parent, child)
    assert merged.requirement.summary == "sub-done"
    assert seen["child_req"] == "sub-done"


@pytest.mark.asyncio
async def test_compiled_graph_bubbles_escaped_verdict():
    class _Repair:
        name = "inner_repair"; phase = Phase.IMPLEMENTING
        async def run(self, ctx):
            return NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint="h"))
    reg = NodeRegistry(); reg.register(_Repair())
    # no PLAN back-edge inside → inner route ESCAPEs → bubble
    sub = Graph(nodes=reg, edges=EdgeTable(forward={}, back_edges={}), entry="inner_repair")
    cg = CompiledGraph(
        sub, name="sub",
        fork=lambda p: replace(p, cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="inner_repair")),
        merge=lambda p, c: p)
    parent = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="sub"))
    result = await cg.run(NodeContext(state=parent, cancel=asyncio.Event()))
    assert result.output is None
    assert result.verdict is not None and result.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_compiled_graph_exit_branch():
    cg = CompiledGraph(
        _sub_graph(), name="sub",
        fork=lambda p: replace(p, cursor=Cursor(phase=Phase.PLANNING, current_node="inner_producer")),
        merge=lambda p, c: replace(p, requirement=c.requirement),
        exit_branch=lambda child: "done" if child.requirement is not None else None)
    parent = SessionState(cursor=Cursor(phase=Phase.ROUTING, current_node="sub"))
    result = await cg.run(NodeContext(state=parent, cancel=asyncio.Event()))
    assert result.branch == "done"
