from poor_code.ui.widgets.chat_log import _render_segment
from poor_code.ui.store import (
    NodeLabelSegment, NodeResultSegment, UserAnswerSegment,
)


def test_render_node_label_uses_activity():
    seg = NodeLabelSegment(node="explorer", phase="locating",
                           activity="Exploring the codebase")
    out = _render_segment(seg)
    assert "Exploring the codebase" in out


def test_render_node_label_retry_count_shown():
    seg = NodeLabelSegment(node="spec_confirm_gate", phase="interviewing",
                           activity="Confirming the spec with you", retry=2)
    out = _render_segment(seg)
    assert "×3" in out  # retry=2 -> 3rd time


def test_render_gate_node_shows_decision_marker():
    seg = NodeLabelSegment(node="plan_confirm_gate", phase="planning",
                           activity="Confirming the plan with you")
    out = _render_segment(seg)
    assert "⚠" in out


def test_render_node_result_card():
    seg = NodeResultSegment(node="explorer", phase="locating",
                            headline="Found 5 files", detail=("a.py",))
    out = _render_segment(seg)
    assert "⤷" in out and "Found 5 files" in out


def test_render_user_answer():
    seg = UserAnswerSegment(text="the bottom bar")
    out = _render_segment(seg)
    assert "the bottom bar" in out
