from poor_code.domain.harness.sink import TurnSink
from poor_code.messages import NodeEntered, NodeProduced


class _FakeNarrator:
    def activity(self, node, phase, state):
        return f"doing {node}"
    def summary(self, node, result):
        return (f"{node} done", ("x",))


def _collect():
    events = []
    return events, events.append


def test_node_entered_uses_narrator_when_no_explicit_activity():
    events, dispatch = _collect()
    sink = TurnSink("t1", dispatch, narrator=_FakeNarrator())
    sink.node_entered("explorer", "locating", state=object())
    assert isinstance(events[0], NodeEntered)
    assert events[0].activity == "doing explorer"


def test_node_entered_prefers_explicit_activity():
    events, dispatch = _collect()
    sink = TurnSink("t1", dispatch, narrator=_FakeNarrator())
    sink.node_entered("explorer", "locating", state=object(), activity="LLM wrote this")
    assert events[0].activity == "LLM wrote this"


def test_node_entered_without_narrator_empty_activity():
    events, dispatch = _collect()
    sink = TurnSink("t1", dispatch)
    sink.node_entered("explorer", "locating")
    assert events[0].activity == ""


def test_node_produced_dispatches_when_headline_nonempty():
    events, dispatch = _collect()
    sink = TurnSink("t1", dispatch, narrator=_FakeNarrator())
    sink.node_produced("explorer", "locating", result=object())
    assert isinstance(events[0], NodeProduced)
    assert events[0].headline == "explorer done" and events[0].detail == ("x",)


def test_node_produced_skips_when_empty_headline():
    events, dispatch = _collect()
    class Empty:
        def summary(self, n, r): return ("", ())
        def activity(self, n, p, s): return ""
    sink = TurnSink("t1", dispatch, narrator=Empty())
    sink.node_produced("x", "p", result=object())
    assert events == []
