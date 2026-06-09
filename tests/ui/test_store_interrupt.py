from poor_code.ui.store import (
    AppState, NodeLabelSegment, PromptSubmitted, SteeringSubmitted,
    TurnInterrupted, TurnStarted, UserAnswerSegment, reduce,
)


def _running_turn_with_node():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c", user_text="fix"))
    s = reduce(s, TurnStarted(cmd_id="c", turn_id="t"))
    turn = s.turns[0]
    seg = NodeLabelSegment(node="planner", phase="planning", status="running")
    return s.__class__(  # replace turns with one carrying a running node label
        **{**s.__dict__, "turns": (turn.__class__(
            **{**turn.__dict__, "segments": (seg,)}),)})


def test_turn_interrupted_pauses_turn_and_marks_node():
    s = _running_turn_with_node()
    out = reduce(s, TurnInterrupted(turn_id="t"))
    assert out.is_processing is False
    assert out.awaiting_input is False
    assert out.turns[0].status == "paused"
    assert out.turns[0].segments[-1].status == "interrupted"


def test_steering_submitted_resumes_running_and_records_text():
    s = _running_turn_with_node()
    s = reduce(s, TurnInterrupted(turn_id="t"))
    out = reduce(s, SteeringSubmitted(turn_id="t", text="use auth.py"))
    assert out.is_processing is True
    assert out.turns[0].status == "running"
    assert isinstance(out.turns[0].segments[-1], UserAnswerSegment)
    assert out.turns[0].segments[-1].text == "use auth.py"
