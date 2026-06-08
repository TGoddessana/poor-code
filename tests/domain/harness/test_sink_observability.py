import json
from poor_code.domain.harness.sink import TurnSink
from poor_code.domain.harness.trace import TraceSink
from poor_code.domain.session.paths import turn_trace_jsonl
from poor_code.messages import (
    NodeContextCaptured, NodeThinkingDelta, NodeRawOutput, NodeFinished, TurnConcluded,
)


def _collect():
    out = []
    return out, out.append


def test_context_dispatches_event_and_traces(tmp_path):
    out, dispatch = _collect()
    trace = TraceSink(turn_trace_jsonl(tmp_path, "S", "T"))
    sink = TurnSink("T", dispatch, trace=trace)
    sink.node_context("interviewer", "interviewing",
                      [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}])
    ev = next(e for e in out if isinstance(e, NodeContextCaptured))
    assert ev.node == "interviewer" and "msg" in ev.summary
    rec = json.loads(turn_trace_jsonl(tmp_path, "S", "T").read_text().splitlines()[0])
    assert rec["type"] == "node_context" and rec["node"] == "interviewer"


def test_thinking_delta_dispatches_but_not_traced(tmp_path):
    out, dispatch = _collect()
    path = turn_trace_jsonl(tmp_path, "S", "T")
    sink = TurnSink("T", dispatch, trace=TraceSink(path))
    sink.node_thinking_delta("interviewer", '{"q":')
    assert any(isinstance(e, NodeThinkingDelta) for e in out)
    assert not path.exists()  # per-token deltas are NOT written to the trace file


def test_finished_includes_thinking_chars_and_resets(tmp_path):
    out, dispatch = _collect()
    path = turn_trace_jsonl(tmp_path, "S", "T")
    sink = TurnSink("T", dispatch, trace=TraceSink(path))
    sink.node_thinking_delta("n", "abc")
    sink.node_thinking_delta("n", "de")
    sink.node_raw_output("n", "{}")
    sink.node_finished("n", "phase", 1.5, "done")
    assert any(isinstance(e, NodeFinished) for e in out)
    recs = [json.loads(l) for l in path.read_text().splitlines()]
    fin = next(r for r in recs if r["type"] == "node_finished")
    assert fin["thinking_chars"] == 5 and fin["duration_sec"] == 1.5


def test_turn_concluded_dispatch_and_trace(tmp_path):
    out, dispatch = _collect()
    path = turn_trace_jsonl(tmp_path, "S", "T")
    TurnSink("T", dispatch, trace=TraceSink(path)).turn_concluded("parked", "node 'x' not reached")
    assert TurnConcluded(turn_id="T", reason="parked", detail="node 'x' not reached") in out
    assert json.loads(path.read_text().splitlines()[0])["reason"] == "parked"
