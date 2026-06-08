from poor_code.messages import (
    NodeEntered, NodeFinished, NodeContextCaptured, NodeThinkingDelta,
    NodeRawOutput, TurnConcluded, TurnStarted,
)
from poor_code.ui.store import (
    AppState, PromptSubmitted, reduce,
    NodeLabelSegment, NodeContextSegment, NodeThinkingSegment, NodeRawOutputSegment,
)


def _running_turn():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c", user_text="hi"))
    s = reduce(s, TurnStarted(cmd_id="c", turn_id="T"))
    return reduce(s, NodeEntered(turn_id="T", node="interviewer", phase="interviewing", activity="Asking"))


def test_node_finished_pins_duration_and_status():
    s = _running_turn()
    s = reduce(s, NodeFinished(turn_id="T", node="interviewer", phase="interviewing",
                               duration_sec=41.2, status="parked"))
    label = next(seg for seg in s.turns[-1].segments if isinstance(seg, NodeLabelSegment))
    assert label.duration_sec == 41.2 and label.status == "parked"


def test_context_thinking_rawoutput_append():
    s = _running_turn()
    s = reduce(s, NodeContextCaptured(turn_id="T", node="interviewer", summary="sys + 2", full="RAW"))
    s = reduce(s, NodeThinkingDelta(turn_id="T", node="interviewer", text='{"q":'))
    s = reduce(s, NodeThinkingDelta(turn_id="T", node="interviewer", text='"why"}'))
    s = reduce(s, NodeRawOutput(turn_id="T", node="interviewer", raw='{"q":"why"}'))
    segs = s.turns[-1].segments
    assert any(isinstance(x, NodeContextSegment) and x.full == "RAW" for x in segs)
    think = next(x for x in segs if isinstance(x, NodeThinkingSegment))
    assert think.text == '{"q":"why"}'   # deltas accumulate into one segment
    assert any(isinstance(x, NodeRawOutputSegment) and x.raw == '{"q":"why"}' for x in segs)


def test_turn_concluded_sets_state_and_prompt_resets_it():
    s = _running_turn()
    s = reduce(s, TurnConcluded(turn_id="T", reason="parked", detail="node 'composer' not reached"))
    assert s.turn_conclusion == ("parked", "node 'composer' not reached")
    s2 = reduce(s, PromptSubmitted(cmd_id="c2", user_text="next"))
    assert s2.turn_conclusion is None
