import io
import json
import pytest

from poor_code.domain.harness import headless


@pytest.mark.asyncio
async def test_main_no_creds_returns_2(monkeypatch):
    monkeypatch.setattr(headless, "resolve_llm", lambda: None)
    err = io.StringIO()
    code = await headless.main("do something", stdout=io.StringIO(), stderr=err)
    assert code == 2
    assert "login" in err.getvalue().lower() or "credential" in err.getvalue().lower()


@pytest.mark.asyncio
async def test_main_returns_1_and_reports_when_run_raises(monkeypatch):
    monkeypatch.setattr(headless, "resolve_llm", lambda: object())
    monkeypatch.setattr(headless, "_build_driver", lambda llm: object())

    async def boom(driver, state, cancel, sink=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(headless, "run_headless", boom)
    err = io.StringIO()
    code = await headless.main("do something", stdout=io.StringIO(), stderr=err)
    assert code == 1
    assert "kaboom" in err.getvalue()


@pytest.mark.asyncio
async def test_main_runs_graph_and_prints_report_json(monkeypatch, tmp_path):
    from poor_code.domain.session.models import (
        Report, ReportOutcome, SessionState,
    )

    monkeypatch.setattr(headless, "resolve_llm", lambda: object())

    async def fake_run_headless(driver, state, cancel, sink=None):
        return state.with_report(Report(outcome=ReportOutcome.SUCCEEDED,
                                        summary="1/1 tasks done; global validation passed"))

    monkeypatch.setattr(headless, "run_headless", fake_run_headless)
    monkeypatch.setattr(headless, "_build_driver", lambda llm: object())

    out = io.StringIO()
    code = await headless.main("do something", stdout=out, stderr=io.StringIO())
    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["outcome"] == "succeeded"
    assert "1/1" in payload["summary"]
