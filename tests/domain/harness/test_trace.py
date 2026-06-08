import json
from poor_code.domain.harness.trace import TraceSink
from poor_code.domain.session.paths import turn_trace_jsonl


def test_turn_trace_path_under_session(tmp_path):
    p = turn_trace_jsonl(tmp_path, "S1", "T1")
    assert p == tmp_path / "sessions" / "S1" / "turns" / "T1" / "trace.jsonl"


def test_trace_sink_appends_jsonl_with_ts(tmp_path):
    p = turn_trace_jsonl(tmp_path, "S1", "T1")
    sink = TraceSink(p)
    sink.write({"type": "node_entered", "node": "router"})
    sink.write({"type": "turn_concluded", "reason": "completed"})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["type"] == "node_entered" and rec0["node"] == "router"
    assert "ts" in rec0 and isinstance(rec0["ts"], str)


def test_trace_sink_preserves_caller_ts(tmp_path):
    p = turn_trace_jsonl(tmp_path, "S1", "T1")
    TraceSink(p).write({"type": "x", "ts": "2026-06-08T00:00:00+00:00"})
    assert json.loads(p.read_text().splitlines()[0])["ts"] == "2026-06-08T00:00:00+00:00"
