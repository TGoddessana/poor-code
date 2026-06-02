from poor_code.messages import ReportReady
from poor_code.ui.store import AppState, ReportSegment, TurnView, reduce


def _turn_state() -> AppState:
    turn = TurnView(turn_id="t1", cmd_id="c1", user_text="x", status="running")
    return AppState(turns=(turn,), is_processing=True)


def test_report_ready_appends_report_segment():
    st = _turn_state()
    st = reduce(st, ReportReady(turn_id="t1", outcome="succeeded",
                                summary="1/1 tasks done; global validation passed",
                                lines=("A — done",)))
    seg = st.turns[-1].segments[-1]
    assert isinstance(seg, ReportSegment)
    assert seg.outcome == "succeeded"
    assert "A — done" in seg.lines
