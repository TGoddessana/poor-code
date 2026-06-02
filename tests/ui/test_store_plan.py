from poor_code.ui.store import AppState, TurnView, PlanSegment, reduce
from poor_code.messages import PlanReady


def test_plan_ready_appends_plan_segment():
    turn = TurnView(turn_id="T", cmd_id="c", user_text="x", status="running")
    state = AppState(turns=(turn,), is_processing=True)
    out = reduce(state, PlanReady(turn_id="T", lines=("1. do x", "2. do y")))
    seg = out.turns[0].segments[-1]
    assert isinstance(seg, PlanSegment)
    assert seg.lines == ("1. do x", "2. do y")
