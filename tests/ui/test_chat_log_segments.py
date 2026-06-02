from poor_code.ui.store import NodeLabelSegment
from poor_code.ui.widgets.chat_log import _render_segment


def test_render_node_label():
    assert _render_segment(NodeLabelSegment(node="explorer", phase="locating")) == "▸ explorer"
