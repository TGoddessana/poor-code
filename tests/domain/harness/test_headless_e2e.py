"""End-to-end test that drives the full real registry through run_headless
(the production path: cli.main → headless.main → run_headless over the real graph).
Reuses E2ELLM and _map from test_execution_e2e so the scripted LLM is kept in one place."""
import asyncio
import pytest

from tests.domain.harness.test_execution_e2e import E2ELLM, _map

from poor_code.domain.harness import build_default_registry, Driver, route
from poor_code.domain.harness.headless import run_headless
from poor_code.domain.session.models import (
    Cursor, Phase, Policy, Request, RequestKind, ReportOutcome, SessionState,
)


class _TraceSink:
    """Records the node_entered calls so a test can assert the walked path."""

    def __init__(self) -> None:
        self.entered: list[str] = []

    def node_entered(self, node: str, phase: str) -> None:
        self.entered.append(node)

    def __getattr__(self, _name):  # no-op for every other sink method
        return lambda *a, **k: None


@pytest.mark.asyncio
async def test_run_headless_over_real_registry_reaches_succeeded_report(tmp_path):
    llm = E2ELLM()
    reg = build_default_registry(llm=llm, project_map=_map(tmp_path))
    driver = Driver(reg, route)

    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="create out.txt", kind=RequestKind.ENGINEERING),
        policy=Policy.FULL_AUTO,
    )

    sink = _TraceSink()
    final = await run_headless(driver, start, asyncio.Event(), sink=sink)

    assert final.report is not None
    assert final.report.outcome is ReportOutcome.SUCCEEDED
    # the implementer actually created the file in the work tree
    assert (tmp_path / "out.txt").read_text() == "ok"
    # FULL_AUTO skips the human-dialogue interviewer and the LLM adequacy critic, but
    # KEEPS the lean acceptance (oracle + gate) — the issue-grounded independent check
    # that global_validator runs at the end. So the oracle + gate ARE entered.
    for kept in ("acceptance_oracle", "acceptance_gate", "planner",
                 "global_validator", "reporter"):
        assert kept in sink.entered, f"{kept} should run in FULL_AUTO"
    for skipped in ("interviewer", "acceptance_critic"):
        assert skipped not in sink.entered, f"{skipped} should be skipped in FULL_AUTO"
