from poor_code.ui.store import NodeLabelSegment, QuerySegment
from poor_code.ui.widgets.chat_log import _render_segment


def test_render_node_label():
    assert _render_segment(NodeLabelSegment(node="explorer", phase="locating")) == "▸ explorer"


def test_render_query_segment():
    out = _render_segment(QuerySegment(prompt="which?", options=("OAuth", "Session"), kind="choose"))
    assert "which?" in out
    assert "[1] OAuth" in out
    assert "[2] Session" in out
