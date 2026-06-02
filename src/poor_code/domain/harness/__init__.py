"""harness — the graph runtime (control). Imports domain/session (data), never ui/."""
from __future__ import annotations

from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import Node, NodeContext, NodeResult
from poor_code.domain.harness.nodes.gates import PlanGate, UnderstandingGate
from poor_code.domain.harness.nodes.interviewer import Interviewer
from poor_code.domain.harness.nodes.locator import Locator
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.harness.nodes.router import Router
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import FORWARD, route
from poor_code.domain.project_map.models import ProjectMap

__all__ = [
    "Driver", "Node", "NodeContext", "NodeResult", "NodeRegistry",
    "Router", "Locator", "Interviewer", "Planner", "PlanGate",
    "route", "FORWARD", "build_default_registry",
]


def build_default_registry(*, llm, project_map: ProjectMap) -> NodeRegistry:
    """Assemble the v1 planning-layer graph. Composer and beyond are not
    registered yet — the Driver parks there until the execution layer exists."""
    reg = NodeRegistry()
    reg.register(Router(llm))
    reg.register(Locator(llm, project_map=project_map))
    reg.register(UnderstandingGate())
    reg.register(Interviewer(llm, project_map=project_map))
    reg.register(Planner(llm, project_map=project_map))
    reg.register(PlanGate())
    return reg
