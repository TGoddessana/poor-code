from poor_code.messages import NodeEntered, QueryRaised, PlanReady, Event


def test_node_entered_carries_primitives():
    e = NodeEntered(turn_id="t1", node="explorer", phase="locating")
    assert isinstance(e, Event)
    assert (e.turn_id, e.node, e.phase) == ("t1", "explorer", "locating")


def test_query_raised_carries_primitives():
    e = QueryRaised(turn_id="t1", query_id="q1", kind="choose",
                    prompt="which?", options=("a", "b"))
    assert e.options == ("a", "b")
    assert e.query_id == "q1"


def test_plan_ready_carries_lines():
    e = PlanReady(turn_id="t1", lines=("1. do x", "2. do y"))
    assert e.lines[0] == "1. do x"
