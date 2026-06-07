from poor_code.domain.session.models import Phase


def test_router_and_fastpath_have_phase():
    from poor_code.domain.harness.nodes.router import Router
    from poor_code.domain.harness.nodes.fast_path import FastPathNode
    assert getattr(Router, "phase", None) == Phase.ROUTING
    assert getattr(FastPathNode, "phase", None) == Phase.ROUTING


def test_confirm_gates_have_distinct_phases():
    from poor_code.domain.harness.nodes.confirm_gates import (
        SpecConfirmGate, PlanConfirmGate,
    )
    assert getattr(SpecConfirmGate, "phase", None) == Phase.INTERVIEWING
    assert getattr(PlanConfirmGate, "phase", None) == Phase.PLANNING
