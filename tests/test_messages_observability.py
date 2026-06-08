from poor_code.messages import (
    NodeFinished, NodeContextCaptured, NodeThinkingDelta, NodeRawOutput, TurnConcluded,
)


def test_node_finished_fields():
    e = NodeFinished(turn_id="T", node="interviewer", phase="interviewing",
                     duration_sec=41.2, status="parked")
    assert (e.turn_id, e.node, e.duration_sec, e.status) == ("T", "interviewer", 41.2, "parked")


def test_context_thinking_rawoutput_concluded():
    assert NodeContextCaptured(turn_id="T", node="n", summary="s", full="f").full == "f"
    assert NodeThinkingDelta(turn_id="T", node="n", text="{").text == "{"
    assert NodeRawOutput(turn_id="T", node="n", raw="{}").raw == "{}"
    c = TurnConcluded(turn_id="T", reason="parked", detail="node 'composer' not reached")
    assert (c.reason, c.detail) == ("parked", "node 'composer' not reached")
