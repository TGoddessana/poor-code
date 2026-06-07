from poor_code.messages import NodeEntered, NodeProduced
from poor_code.ui.store import (
    AppState, NodeLabelSegment, NodeResultSegment, TurnView, UserAnswerSegment,
    AnswerSubmitted, reduce,
)


def _turn(tid="t1"):
    return TurnView(turn_id=tid, cmd_id="c1", user_text="hi", status="running")


def test_answer_submitted_echoes_user_answer_segment():
    s = AppState(turns=(_turn(),), awaiting_input=True)
    s2 = reduce(s, AnswerSubmitted(turn_id="t1", answer="the bottom bar"))
    segs = s2.turns[0].segments
    assert segs and isinstance(segs[-1], UserAnswerSegment)
    assert segs[-1].text == "the bottom bar"
    assert s2.awaiting_input is False


def test_answer_submitted_ignored_when_not_awaiting():
    s = AppState(turns=(_turn(),), awaiting_input=False)
    assert reduce(s, AnswerSubmitted(turn_id="t1", answer="x")) is s


def test_node_entered_tracks_phase_and_seen():
    s = AppState(turns=(_turn(),))
    s = reduce(s, NodeEntered(turn_id="t1", node="explorer", phase="locating",
                              activity="Exploring the codebase"))
    assert s.current_phase == "locating"
    assert s.phases_seen == ("locating",)
    seg = s.turns[0].segments[-1]
    assert isinstance(seg, NodeLabelSegment)
    assert seg.node == "explorer" and seg.activity == "Exploring the codebase"


def test_node_entered_dedupes_consecutive_same_node_with_retry_count():
    s = AppState(turns=(_turn(),))
    ev = NodeEntered(turn_id="t1", node="spec_confirm_gate", phase="interviewing",
                     activity="Confirming the spec with you")
    s = reduce(s, ev)
    s = reduce(s, ev)
    s = reduce(s, ev)
    labels = [x for x in s.turns[0].segments if isinstance(x, NodeLabelSegment)]
    assert len(labels) == 1
    assert labels[0].retry == 2  # entered 3x → 2 retries


def test_node_entered_new_segment_when_node_changes():
    s = AppState(turns=(_turn(),))
    s = reduce(s, NodeEntered(turn_id="t1", node="planner", phase="planning", activity="a"))
    s = reduce(s, NodeEntered(turn_id="t1", node="acceptance_oracle", phase="planning", activity="b"))
    labels = [x for x in s.turns[0].segments if isinstance(x, NodeLabelSegment)]
    assert len(labels) == 2


def test_node_produced_appends_result_segment():
    s = AppState(turns=(_turn(),))
    s = reduce(s, NodeProduced(turn_id="t1", node="explorer", phase="locating",
                               headline="5 files / 2 tests", detail=("a.py",)))
    seg = s.turns[0].segments[-1]
    assert isinstance(seg, NodeResultSegment)
    assert seg.headline == "5 files / 2 tests" and seg.detail == ("a.py",)
