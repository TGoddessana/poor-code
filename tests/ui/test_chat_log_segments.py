from poor_code.ui.store import NodeLabelSegment, PlanSegment, QuerySegment, UserAnswerSegment
from poor_code.ui.widgets.chat_log import _render_segment


def test_render_plan_segment():
    out = _render_segment(PlanSegment(lines=("1. do x", "2. do y")))
    assert "📋" in out
    assert "1. do x" in out
    assert "2. do y" in out


def test_render_node_label():
    assert _render_segment(NodeLabelSegment(node="explorer", phase="locating")) == "▸ explorer"


def test_render_finished_node_label_includes_duration():
    out = _render_segment(NodeLabelSegment(
        node="explorer", phase="locating", duration_sec=1.234, status="done"))
    assert out == "▸ explorer  1.2s"


def test_render_query_segment():
    out = _render_segment(QuerySegment(prompt="which?", options=("OAuth", "Session"), kind="choose"))
    assert "which?" in out
    assert "[1] OAuth" in out
    assert "[2] Session" in out


def test_render_user_answer_and_steering_are_distinct():
    answer = _render_segment(UserAnswerSegment(text="because", kind="answer"))
    steering = _render_segment(UserAnswerSegment(text="wrong question", kind="steering"))
    assert "Answer: because" in answer
    assert "Steering: wrong question" in steering


def test_query_segment_renders_context_and_rationale_lines():
    seg = QuerySegment(prompt="which?", options=("A", "B"), kind="choose",
                       context="only one entrypoint", rationale="decides build target")
    text = _render_segment(seg)
    assert "which?" in text
    assert "only one entrypoint" in text
    assert "decides build target" in text
    assert "[1] A" in text and "[2] B" in text


def test_query_segment_without_context_omits_those_lines():
    seg = QuerySegment(prompt="why?", options=(), kind="clarify")
    text = _render_segment(seg)
    assert text.splitlines()[0].endswith("why?")
    assert "맥락" not in text and "왜" not in text
