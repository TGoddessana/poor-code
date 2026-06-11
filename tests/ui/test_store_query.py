from poor_code.ui.store import (
    AppState, TurnView, QuerySegment, UserAnswerSegment, AnswerSubmitted, reduce,
)
from poor_code.messages import QueryRaised


def _running():
    turn = TurnView(turn_id="T", cmd_id="c", user_text="x", status="running")
    return AppState(turns=(turn,), is_processing=True)


def test_query_raised_appends_segment_and_sets_awaiting():
    state = reduce(_running(), QueryRaised(
        turn_id="T", query_id="q1", kind="choose", prompt="which?", options=("a", "b")))
    seg = state.turns[0].segments[-1]
    assert isinstance(seg, QuerySegment)
    assert seg.prompt == "which?" and seg.options == ("a", "b") and seg.kind == "choose"
    assert state.awaiting_input is True
    assert state.is_processing is True  # the long turn stays open


def test_answer_submitted_clears_awaiting():
    state = reduce(_running(), QueryRaised(
        turn_id="T", query_id="q1", kind="clarify", prompt="why?"))
    state = reduce(state, AnswerSubmitted(turn_id="T", answer="because"))
    assert state.awaiting_input is False
    assert isinstance(state.turns[0].segments[-1], UserAnswerSegment)
    assert state.turns[0].segments[-1].text == "because"
    assert state.turns[0].segments[-1].kind == "answer"
