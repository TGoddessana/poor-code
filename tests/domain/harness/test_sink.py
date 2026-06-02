from poor_code.domain.harness.sink import TurnSink
from poor_code.domain.session.models import Plan, Task, EditScope, Query, QueryKind
from poor_code.messages import (
    AssistantTextDelta, NodeEntered, QueryRaised, PlanReady,
    ToolCallStarted, TurnStarted, TurnEnded,
)


def _collect():
    out = []
    return out, out.append


def test_node_facing_methods_stamp_turn_id():
    out, dispatch = _collect()
    sink = TurnSink("T", dispatch)
    sink.node_entered("explorer", "locating")
    sink.text_delta("hello")
    sink.tool_started("c1", "read", {"path": "a.py"})
    assert out[0] == NodeEntered(turn_id="T", node="explorer", phase="locating")
    assert out[1] == AssistantTextDelta(turn_id="T", text="hello")
    assert isinstance(out[2], ToolCallStarted) and out[2].turn_id == "T"


def test_text_delta_ignores_empty():
    out, dispatch = _collect()
    TurnSink("T", dispatch).text_delta("")
    assert out == []


def test_query_raised_extracts_primitives():
    out, dispatch = _collect()
    q = Query(id="q1", kind=QueryKind.CHOOSE, prompt="which?", options=("a", "b"))
    TurnSink("T", dispatch).query_raised(q)
    assert out == [QueryRaised(turn_id="T", query_id="q1", kind="choose",
                               prompt="which?", options=("a", "b"))]


def test_plan_ready_formats_lines():
    out, dispatch = _collect()
    plan = Plan(tasks=(Task(id="t1", title="Add X", purpose="p",
                            edit_scope=EditScope(editable=("a.py",)),
                            how_to_validate="pytest"),))
    TurnSink("T", dispatch).plan_ready(plan)
    assert isinstance(out[0], PlanReady)
    assert out[0].lines == ("1. Add X — edits: a.py — validate: pytest",)


def test_forward_drops_turn_envelope_and_restamps():
    out, dispatch = _collect()
    sink = TurnSink("T", dispatch)
    sink.forward(TurnStarted(cmd_id="c", turn_id="OTHER"))
    sink.forward(TurnEnded(turn_id="OTHER", duration_sec=1.0, model="m"))
    sink.forward(AssistantTextDelta(turn_id="OTHER", text="hi"))
    assert out == [AssistantTextDelta(turn_id="T", text="hi")]
