"""harness — the graph runtime (control). Imports domain/session (data), never ui/.
All execution agent nodes (composer, implementer, validator, failure_analyst,
global_validator) are registered; the full graph runs to the 'reporter' park."""
from __future__ import annotations

from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.graph import EdgeTable, Graph
from poor_code.domain.harness.node import Node, NodeContext, NodeResult
from poor_code.domain.harness.nodes.acceptance_critic import AcceptanceCritic
from poor_code.domain.harness.nodes.acceptance_oracle import AcceptanceOracle
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.harness.nodes.fast_path import FastPathNode
from poor_code.domain.harness.nodes.gates import AcceptanceGate, PlanGate, UnderstandingGate
from poor_code.domain.harness.nodes.global_validator import GlobalValidator
from poor_code.domain.harness.nodes.interviewer import Interviewer
from poor_code.domain.harness.nodes.plan_reviewer import PlanReviewer
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.harness.nodes.provisioner import Provisioner
from poor_code.domain.harness.nodes.reporter import Reporter
from poor_code.domain.harness.nodes.router import Router
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import FORWARD, route
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.glob import GlobTool
from poor_code.domain.tool.grep import GrepTool
from poor_code.domain.tool.list import ListTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry

__all__ = [
    "Driver", "Node", "NodeContext", "NodeResult", "NodeRegistry",
    "Router", "ExploringNode", "Interviewer", "Planner", "PlanGate", "FastPathNode",
    "AcceptanceOracle", "AcceptanceGate", "AcceptanceCritic",
    "GlobalValidator", "Reporter",
    "Provisioner",
    "route", "FORWARD", "build_default_registry",
    "Graph", "EdgeTable", "build_default_graph",
]


def build_default_registry(*, llm, project_map: ProjectMap, agent=None) -> NodeRegistry:
    """Assemble the full planning+execution-layer graph. All agent nodes are
    registered: Router, ExploringNode, Interviewer, Planner, TaskSelector,
    Composer, Implementer, Validator, FailureAnalyst, GlobalValidator plus the
    deterministic gates and runners. The graph runs to the 'reporter' park.
    When `agent` is provided, the lightweight leaf (fast_path) is also registered."""
    reg = NodeRegistry()
    reg.register(Router(llm))
    reg.register(ExploringNode(
        llm, project_map=project_map,
        tools=ToolRegistry([ListTool(), GlobTool(), ReadTool(), GrepTool()])))
    reg.register(UnderstandingGate())
    reg.register(Interviewer(llm, project_map=project_map))
    reg.register(AcceptanceOracle(llm))
    reg.register(AcceptanceGate())
    reg.register(AcceptanceCritic(llm))
    reg.register(Planner(llm, project_map=project_map))
    reg.register(PlanGate())
    reg.register(PlanReviewer(llm))
    reg.register(Provisioner(
        llm, cwd=project_map.cwd,
        tools=ToolRegistry([BashTool(), ReadTool(), ListTool(), GlobTool(), GrepTool()])))
    # The whole task-execution loop (task_selector→composer→implementer→eng_gate→
    # validator→validation_runner→{completion_gate|failure_analyst}→…) is folded into
    # ONE subgraph node. Its 8 inner nodes are registered inside the subgraph, not here.
    from poor_code.domain.harness.subgraphs.implement_loop import build_implement_loop
    reg.register(build_implement_loop(llm=llm, cwd=project_map.cwd))
    reg.register(GlobalValidator(llm, cwd=project_map.cwd))
    reg.register(Reporter())
    if agent is not None:
        reg.register(FastPathNode(agent))
    return reg


def build_default_graph(*, llm, project_map: ProjectMap, agent=None) -> Graph:
    """진입 그래프(Graph): 기본 레지스트리 + DEFAULT_EDGES + entry='router'."""
    from poor_code.domain.harness.route import DEFAULT_EDGES
    reg = build_default_registry(llm=llm, project_map=project_map, agent=agent)
    return Graph(nodes=reg, edges=DEFAULT_EDGES, entry="router")
