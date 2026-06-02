"""harness — the graph runtime (control). Imports domain/session (data), never ui/.
The graph parks at 'composer' (unregistered) — reached via task_selector — until
Plan 3 adds the agent nodes."""
from __future__ import annotations

from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import Node, NodeContext, NodeResult
from poor_code.domain.harness.nodes.execution import (
    TaskSelector, EngGate, ValidationRunner, CompletionGate,
)
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.harness.nodes.fast_path import FastPathNode
from poor_code.domain.harness.nodes.gates import PlanGate, UnderstandingGate
from poor_code.domain.harness.nodes.interviewer import Interviewer
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.harness.nodes.router import Router
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import FORWARD, route
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.tool.grep import GrepTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry

__all__ = [
    "Driver", "Node", "NodeContext", "NodeResult", "NodeRegistry",
    "Router", "ExploringNode", "Interviewer", "Planner", "PlanGate", "FastPathNode",
    "TaskSelector", "EngGate", "ValidationRunner", "CompletionGate",
    "route", "FORWARD", "build_default_registry",
]


def build_default_registry(*, llm, project_map: ProjectMap, agent=None) -> NodeRegistry:
    """Assemble the v1 planning+execution-layer graph. Agent nodes (composer,
    implementer, validator, failure_analyst, global_validator) are not registered
    yet — the Driver parks at 'composer' until Plan 3 adds them.
    When `agent` is provided, the lightweight leaf (fast_path) is registered;
    otherwise a lightweight classification parks (no output)."""
    reg = NodeRegistry()
    reg.register(Router(llm))
    reg.register(ExploringNode(
        llm, project_map=project_map,
        tools=ToolRegistry([ReadTool(), GrepTool()])))
    reg.register(UnderstandingGate())
    reg.register(Interviewer(llm, project_map=project_map))
    reg.register(Planner(llm, project_map=project_map))
    reg.register(PlanGate())
    reg.register(TaskSelector())
    reg.register(EngGate())
    reg.register(ValidationRunner(cwd=project_map.cwd))
    reg.register(CompletionGate())
    if agent is not None:
        reg.register(FastPathNode(agent))
    return reg
