from poor_code.domain.harness.nodes.reporter import build_report
from poor_code.domain.session.models import SessionState, ReportOutcome


def test_build_report_includes_note():
    report = build_report(SessionState(), ReportOutcome.ABANDONED,
                          note="parked at fast_path: not registered")
    assert "fast_path" in report.summary
