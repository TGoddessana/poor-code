import asyncio

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.gates import AcceptanceGate
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Layer, SessionState, Transition, TriggerKind,
    VerdictKind,
)


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


def _spec(*commands):
    return AcceptanceSpec(checks=tuple(
        AcceptanceCheck(criterion=f"c{i}", command=c) for i, c in enumerate(commands)))


@pytest.mark.asyncio
async def test_advances_on_well_formed_spec():
    s = SessionState(acceptance=_spec("printf '%s' \"$E\" | diff - hello.txt"))
    res = await AcceptanceGate().run(_ctx(s))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_repairs_on_empty_spec():
    res = await AcceptanceGate().run(_ctx(SessionState(acceptance=AcceptanceSpec())))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.ACCEPTANCE


@pytest.mark.asyncio
async def test_repairs_on_prose_check():
    s = SessionState(acceptance=_spec("Check that hello.txt is correct"))
    res = await AcceptanceGate().run(_ctx(s))
    assert res.verdict.kind is VerdictKind.REPAIR
    assert res.verdict.layer is Layer.ACCEPTANCE


def _bounces(n):
    return tuple(
        Transition(from_node="acceptance_gate", to_node="acceptance_oracle",
                   trigger=TriggerKind.GATE, reason="r", ts_iso="t")
        for _ in range(n))


@pytest.mark.asyncio
async def test_repairs_well_under_budget():
    # Budget is now 100 — a few prior bounces must still REPAIR, not escalate.
    s = SessionState(acceptance=AcceptanceSpec(), history=_bounces(5))
    res = await AcceptanceGate().run(_ctx(s))
    assert res.verdict.kind is VerdictKind.REPAIR


@pytest.mark.asyncio
async def test_escalates_after_budget():
    from poor_code.domain.harness.nodes.gates import ACCEPTANCE_REPAIR_BUDGET
    assert ACCEPTANCE_REPAIR_BUDGET == 100
    s = SessionState(acceptance=AcceptanceSpec(), history=_bounces(ACCEPTANCE_REPAIR_BUDGET))
    res = await AcceptanceGate().run(_ctx(s))
    assert res.verdict.kind is VerdictKind.ESCALATE


# --- unknown-status abstention tests ---

def test_gate_allows_unknown_check_with_empty_command():
    """A spec with a verified check plus an unknown-status empty-command check must PASS."""
    spec = AcceptanceSpec(checks=(
        AcceptanceCheck(criterion="core works", command="pytest -q", status="verified"),
        AcceptanceCheck(criterion="hard value exact", command="", status="unknown"),
    ))
    assert AcceptanceGate()._invalid_hint(spec) is None


def test_gate_allows_spec_with_only_unknown_checks():
    """A spec whose sole check is an unknown-status empty-command check must PASS
    (oracle abstained on all criteria; at least one check is present)."""
    spec = AcceptanceSpec(checks=(
        AcceptanceCheck(criterion="some criterion", command="", status="unknown"),
    ))
    assert AcceptanceGate()._invalid_hint(spec) is None


def test_gate_still_rejects_verified_check_with_empty_command():
    """Regression guard: a verified-status check with no command must still be REJECTED."""
    spec = AcceptanceSpec(checks=(
        AcceptanceCheck(criterion="core works", command="", status="verified"),
    ))
    assert AcceptanceGate()._invalid_hint(spec) is not None


def test_gate_still_rejects_empty_spec():
    """A spec with no checks at all must still be REJECTED."""
    assert AcceptanceGate()._invalid_hint(AcceptanceSpec()) is not None
    assert AcceptanceGate()._invalid_hint(None) is not None
