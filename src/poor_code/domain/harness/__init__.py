"""harness — the graph runtime (control). Imports domain/session (data), never ui/.
All execution agent nodes (composer, implementer, validator, failure_analyst,
global_validator) are registered; the full graph runs to the 'reporter' park."""
from __future__ import annotations

from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import Node, NodeContext, NodeResult
from poor_code.domain.harness.nodes.acceptance_critic import AcceptanceCritic
from poor_code.domain.harness.nodes.acceptance_oracle import AcceptanceOracle
from poor_code.domain.harness.nodes.composer import Composer
from poor_code.domain.harness.nodes.execution import (
    TaskSelector, EngGate, ValidationRunner, CompletionGate,
)
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.harness.nodes.failure_analyst import FailureAnalyst
from poor_code.domain.harness.nodes.fast_path import FastPathNode
from poor_code.domain.harness.nodes.gates import AcceptanceGate, PlanGate, UnderstandingGate
from poor_code.domain.harness.nodes.global_validator import GlobalValidator
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.harness.nodes.interviewer import Interviewer
from poor_code.domain.harness.nodes.plan_reviewer import PlanReviewer
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.harness.nodes.reporter import Reporter
from poor_code.domain.harness.nodes.router import Router
from poor_code.domain.harness.nodes.validator import Validator
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import FORWARD, route
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.edit import EditTool
from poor_code.domain.tool.glob import GlobTool
from poor_code.domain.tool.grep import GrepTool
from poor_code.domain.tool.list import ListTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.write import WriteTool

__all__ = [
    "Driver", "Node", "NodeContext", "NodeResult", "NodeRegistry",
    "Router", "ExploringNode", "Interviewer", "Planner", "PlanGate", "FastPathNode",
    "AcceptanceOracle", "AcceptanceGate", "AcceptanceCritic",
    "TaskSelector", "EngGate", "ValidationRunner", "CompletionGate",
    "Composer", "Implementer", "Validator", "FailureAnalyst", "GlobalValidator", "Reporter",
    "route", "FORWARD", "build_default_registry",
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
    reg.register(TaskSelector())
    reg.register(EngGate())
    reg.register(ValidationRunner(cwd=project_map.cwd))
    reg.register(CompletionGate())
    reg.register(Composer())
    reg.register(Implementer(
        llm, cwd=project_map.cwd,
        tools=ToolRegistry([WriteTool(), EditTool(), BashTool()])))
    reg.register(Validator(llm))
    reg.register(FailureAnalyst(llm))
    reg.register(GlobalValidator(llm, cwd=project_map.cwd))
    reg.register(Reporter())
    if agent is not None:
        reg.register(FastPathNode(agent))
    return reg
