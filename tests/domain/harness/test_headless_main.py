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


@pytest.mark.asyncio
async def test_main_attaches_token_usage_from_meter(monkeypatch):
    """results.json must carry real token counts (they were always 0). main reads
    the run's meter off the client and attaches the snapshot."""
    from poor_code.domain.session.models import Report, ReportOutcome
    from poor_code.provider.events import UsageEnded
    from poor_code.provider.usage import TokenMeter

    class _LLMWithMeter:
        def __init__(self):
            self.meter = TokenMeter()

    llm = _LLMWithMeter()
    llm.meter.record(UsageEnded(input_tokens=300, output_tokens=80,
                                cached_input_tokens=120), label="planner")

    monkeypatch.setattr(headless, "resolve_llm", lambda: llm)
    monkeypatch.setattr(headless, "_build_driver", lambda llm: object())

    async def fake_run_headless(driver, state, cancel, sink=None):
        return state.with_report(Report(outcome=ReportOutcome.SUCCEEDED, summary="done"))

    monkeypatch.setattr(headless, "run_headless", fake_run_headless)

    out = io.StringIO()
    code = await headless.main("do something", stdout=out, stderr=io.StringIO())
    assert code == 0
    err = io.StringIO()
    out2 = io.StringIO()
    monkeypatch.setattr(headless, "resolve_llm", lambda: llm)
    code = await headless.main("do something", stdout=out2, stderr=err)
    payload = json.loads(out2.getvalue())
    assert payload["token_usage"]["total"]["input_tokens"] == 300
    assert payload["token_usage"]["total"]["cached_input_tokens"] == 120
    assert payload["token_usage"]["by_node"]["planner"]["output_tokens"] == 80
    # human-readable trace line for reading bench logs
    assert "tokens" in err.getvalue().lower()
