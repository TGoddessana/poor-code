from poor_code.provider.registry import ModelMeta, ModelPricing
from poor_code.ui.store import AppState, UsageState, ProjectMapStatus
from poor_code.ui.widgets.status_footer import StatusFooter, _k


def test_k_under_1000():
    assert _k(0) == "0"
    assert _k(500) == "500"
    assert _k(999) == "999"


def test_k_over_1000():
    assert _k(1000) == "1.0k"
    assert _k(4521) == "4.5k"
    assert _k(128_000) == "128.0k"


def test_status_footer_format_with_meta_and_usage():
    meta = ModelMeta(
        model_id="gpt-4o",
        context_size=128_000,
        max_output=16384,
        pricing=ModelPricing(input_per_1m=2.5, output_per_1m=10.0),
    )
    state = AppState(
        model="gpt-4o",
        model_meta=meta,
        usage=UsageState(input_tokens=4200, output_tokens=1100, cost_usd=0.034),
        last_turn_tokens=5300,
    )
    text = StatusFooter._format(state)
    assert "4.2k" in text
    assert "1.1k" in text
    assert "$0.0340" in text
    assert "4%" in text
    assert "128.0k" in text
    assert "gpt-4o" in text


def test_status_footer_no_meta_renders_unknown_ctx():
    state = AppState(model=None, model_meta=None, usage=UsageState())
    text = StatusFooter._format(state)
    assert "?/?" in text


def test_ctx_pct_returns_none_when_no_meta():
    state = AppState(model_meta=None, last_turn_tokens=1000)
    assert StatusFooter._ctx_pct(state) is None


def test_ctx_pct_computes_from_last_turn_tokens():
    meta = ModelMeta(model_id="m", context_size=200_000, max_output=4096)
    state = AppState(model_meta=meta, last_turn_tokens=100_000)
    assert StatusFooter._ctx_pct(state) == 50.0


def test_footer_omits_map_when_project_map_is_none():
    state = AppState(model="claude")
    rendered = StatusFooter._format(state)
    assert "map" not in rendered


def test_footer_renders_indexing_with_progress_counts():
    state = AppState(
        model="claude",
        project_map=ProjectMapStatus(phase="indexing", files_processed=12, files_total=87),
    )
    rendered = StatusFooter._format(state)
    assert "map: 12/87" in rendered


def test_footer_renders_ready_clean():
    state = AppState(
        model="claude",
        project_map=ProjectMapStatus(
            phase="ready", files_processed=87, files_total=87,
            parse_error_count=0,
        ),
    )
    rendered = StatusFooter._format(state)
    assert "map: 87 files" in rendered
    assert "errors" not in rendered


def test_footer_renders_ready_with_errors():
    state = AppState(
        model="claude",
        project_map=ProjectMapStatus(
            phase="ready", files_processed=87, files_total=87,
            parse_error_count=2,
        ),
    )
    rendered = StatusFooter._format(state)
    assert "map: 87 files, 2 errors" in rendered


def test_footer_renders_failed():
    state = AppState(
        model="claude",
        project_map=ProjectMapStatus(phase="failed", error="cwd unreadable"),
    )
    rendered = StatusFooter._format(state)
    assert "map: failed" in rendered


def test_footer_shows_awaiting_input():
    s = AppState(awaiting_input=True, is_processing=True)
    assert "awaiting your answer" in StatusFooter._format(s)


def test_footer_shows_current_phase_while_processing():
    s = AppState(is_processing=True, current_phase="planning")
    out = StatusFooter._format(s)
    assert "Planning" in out


def test_footer_shows_last_error():
    s = AppState(last_error="boom")
    assert "boom" in StatusFooter._format(s)
