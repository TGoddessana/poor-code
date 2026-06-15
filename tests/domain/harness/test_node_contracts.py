from poor_code.domain.harness.nodes.router import Router
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.harness.nodes.interviewer import Interviewer
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.harness.nodes.acceptance_oracle import AcceptanceOracle
from poor_code.domain.harness.nodes.reporter import Reporter
from poor_code.domain.harness.nodes.gates import PlanGate
from poor_code.domain.session.models import (
    Request, CodeContext, Requirement, AcceptanceSpec, Plan, Report,
)


def test_top_level_nodes_declare_produces():
    assert Request in Router.produces
    assert CodeContext in ExploringNode.produces
    assert Requirement in Interviewer.produces
    assert AcceptanceSpec in AcceptanceOracle.produces
    assert Plan in Planner.produces
    assert Report in Reporter.produces


def test_nodes_declare_requires():
    assert Request in Router.requires
    assert Requirement in Planner.requires
    assert CodeContext in Planner.requires
    assert AcceptanceSpec in Planner.requires
    assert Plan in PlanGate.requires


def test_base_defaults_exist():
    from poor_code.domain.harness.node import AgentNode, GateNode
    assert AgentNode.requires == ()
    assert AgentNode.produces == ()
    assert GateNode.requires == ()
    assert GateNode.produces == ()
