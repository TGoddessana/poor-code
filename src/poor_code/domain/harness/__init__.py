"""harness — the graph runtime (control). Imports domain/session (data), never ui/.
The task-execution loop (composer, implementer, validator, failure_analyst, …) is
folded into the `implement_loop` subgraph node; global_validator and the planning/
understanding nodes are registered at the top level. The full graph runs to 'reporter'."""
from __future__ import annotations

import warnings

from poor_code.domain.harness.contracts import contract_warnings
from poor_code.domain.harness.driver import Driver, DriverRuntime
from poor_code.domain.harness.graph import CompiledGraph, EdgeTable, Graph
from poor_code.domain.harness.node import (
    AgentNode, Completion, Node, NodeContext, NodeResult, StructuredCompletion,
)
from poor_code.domain.harness.nodes.confirm_gates import PlanConfirmGate, SpecConfirmGate
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.harness.nodes.fast_path import FastPathNode
from poor_code.domain.harness.nodes.gates import PlanGate, UnderstandingGate
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
    "AgentNode", "Completion", "StructuredCompletion", "CompiledGraph",
    "Driver", "DriverRuntime", "Node", "NodeContext", "NodeResult", "NodeRegistry",
    "Router", "ExploringNode", "Interviewer", "Planner", "PlanGate", "FastPathNode",
    "SpecConfirmGate", "PlanConfirmGate",
    "GlobalValidator", "Reporter",
    "Provisioner",
    "route", "FORWARD", "build_default_registry",
    "Graph", "EdgeTable", "build_default_graph",
]


def build_default_registry(*, llm, project_map: ProjectMap, agent=None) -> NodeRegistry:
    """Assemble the full planning+execution-layer graph. Top-level agent nodes:
    Router, ExploringNode, Interviewer, Planner, PlanReviewer,
    Provisioner, GlobalValidator, plus the deterministic gates. The task-execution loop
    (TaskSelector, Composer, Implementer, Validator, FailureAnalyst, runners) is folded
    into the `implement_loop` subgraph node, not registered here. The graph runs to the
    'reporter' park. When `agent` is provided, the lightweight leaf (fast_path) is added."""
    reg = NodeRegistry()
    reg.register(Router(llm))
    reg.register(ExploringNode(
        llm, project_map=project_map,
        tools=ToolRegistry([ListTool(), GlobTool(), ReadTool(), GrepTool()])))
    reg.register(UnderstandingGate())
    reg.register(Interviewer(
        llm, project_map=project_map,
        tools=ToolRegistry([ReadTool(), GrepTool(), GlobTool(), ListTool()])))
    reg.register(SpecConfirmGate())
    reg.register(Planner(llm, project_map=project_map))
    reg.register(PlanGate())
    reg.register(PlanReviewer(llm))
    reg.register(PlanConfirmGate())
    reg.register(Provisioner(
        llm, cwd=project_map.cwd,
        tools=ToolRegistry([BashTool(), ReadTool(), ListTool(), GlobTool(), GrepTool()])))
    # The whole task-execution loop (task_selector→composer→implementer→verifier) is
    # folded into ONE subgraph node. Its inner nodes are registered inside the subgraph,
    # not here. (eng_gate was removed: its git-diff "no patch" floor false-abandoned
    # git-invisible work; the observing Verifier owns done-ness now.)
    from poor_code.domain.harness.subgraphs.implement_loop import build_implement_loop
    reg.register(build_implement_loop(llm=llm, cwd=project_map.cwd))
    # global_validator v2: a whole-build observation-grounded finishing validator (drives
    # the integrated system, hunts cross-task regressions) — gets observe-only tools.
    from poor_code.domain.harness.nodes.global_validator import observe_tools
    reg.register(GlobalValidator(llm, cwd=project_map.cwd, tools=observe_tools()))
    reg.register(Reporter())
    if agent is not None:
        reg.register(FastPathNode(agent))
    for _w in contract_warnings(reg):
        warnings.warn(_w, stacklevel=2)
    return reg


def build_default_graph(*, llm, project_map: ProjectMap, agent=None) -> Graph:
    """진입 그래프(Graph): 기본 레지스트리 + DEFAULT_EDGES + entry='router'."""
    from poor_code.domain.harness.route import DEFAULT_EDGES
    reg = build_default_registry(llm=llm, project_map=project_map, agent=agent)
    return Graph(nodes=reg, edges=DEFAULT_EDGES, entry="router")
