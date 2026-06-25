from poor_code.domain.harness.route import route
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.session.models import (
    SessionState, Verdict, VerdictKind, Layer)


def test_plan_layer_repair_routes_to_planner():
    # The implementer's repair_plan uses the SAME verdict the verifier already emits;
    # at the top-level edge table a PLAN-layer REPAIR bounces to the planner.
    res = NodeResult(verdict=Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN,
                                     hint="re-plan"))
    assert route("implementer", res, SessionState()) == "planner"
