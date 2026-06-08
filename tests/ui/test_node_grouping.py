from poor_code.ui.store import (
    NodeLabelSegment, NodeContextSegment, NodeThinkingSegment, NodeRawOutputSegment,
    TextSegment,
)
from poor_code.ui.widgets.chat_log import group_segments


def test_segments_group_under_their_node_label():
    segs = [
        TextSegment(text="preamble"),                       # before any node → ungrouped
        NodeLabelSegment(node="router", phase="routing"),
        NodeContextSegment(summary="s", full="f"),
        NodeThinkingSegment(text="{...}"),
        NodeLabelSegment(node="explorer", phase="locating"),
        NodeRawOutputSegment(raw="{}"),
    ]
    groups = group_segments(segs)
    # groups: [ (None, [TextSegment]), (router-label, [ctx, think]), (explorer-label, [raw]) ]
    assert groups[0].label is None and len(groups[0].body) == 1
    assert groups[1].label.node == "router" and len(groups[1].body) == 2
    assert groups[2].label.node == "explorer" and len(groups[2].body) == 1


def test_empty_segments_yield_no_groups():
    assert group_segments([]) == []
