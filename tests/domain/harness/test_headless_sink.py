# tests/domain/harness/test_headless_sink.py
import io
from poor_code.domain.harness.headless import StderrSink


def test_stderr_sink_writes_node_and_tool_lines():
    buf = io.StringIO()
    sink = StderrSink(stream=buf)
    sink.node_entered("implementer", "implementing")
    sink.tool_started("c1", "write", {"path": "a.py"})
    sink.tool_finished("c1", "ok")
    sink.tool_failed("c2", "ERROR: boom")
    out = buf.getvalue()
    assert "implementer" in out
    assert "write" in out
    assert "boom" in out


def test_stderr_sink_text_delta_is_quiet_safe():
    buf = io.StringIO()
    sink = StderrSink(stream=buf)
    sink.text_delta("")          # empty: no crash, no output line
    sink.text_delta("hello")
    assert "hello" in buf.getvalue()
