from poor_code.ui.store import (
    AppState, TurnView, NodeLabelSegment, reduce,
)
from poor_code.messages import NodeEntered


def _state_with_running_turn():
    turn = TurnView(turn_id="T", cmd_id="c", user_text="x", status="running")
    return AppState(turns=(turn,), is_processing=True)


def test_node_entered_appends_label_segment():
    state = reduce(_state_with_running_turn(), NodeEntered(turn_id="T", node="explorer", phase="locating"))
    seg = state.turns[0].segments[-1]
    assert isinstance(seg, NodeLabelSegment)
    assert seg.node == "explorer" and seg.phase == "locating"


def test_node_entered_unknown_turn_is_noop():
    state = _state_with_running_turn()
    out = reduce(state, NodeEntered(turn_id="NOPE", node="x", phase="y"))
    assert out is state
