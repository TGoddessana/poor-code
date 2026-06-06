from poor_code.provider.events import UsageEnded
from poor_code.provider.usage import TokenMeter, TokenUsage, tag


class _HasLabel:
    active_label = None


def test_tag_sets_active_label_when_supported():
    obj = _HasLabel()
    tag(obj, "planner")
    assert obj.active_label == "planner"


def test_tag_is_noop_on_clients_without_active_label():
    # Fake LLM clients in tests don't carry a meter/label — tagging must not raise.
    class _Bare:
        __slots__ = ()
    tag(_Bare(), "planner")  # no exception


def test_token_usage_add_combines_all_fields():
    a = TokenUsage(input_tokens=10, output_tokens=5, cached_input_tokens=3, calls=1)
    b = TokenUsage(input_tokens=20, output_tokens=7, cached_input_tokens=4, calls=1)
    c = a + b
    assert c == TokenUsage(input_tokens=30, output_tokens=12,
                           cached_input_tokens=7, calls=2)


def test_token_usage_from_event_counts_one_call():
    u = TokenUsage.from_event(
        UsageEnded(input_tokens=100, output_tokens=40, cached_input_tokens=60))
    assert u == TokenUsage(input_tokens=100, output_tokens=40,
                           cached_input_tokens=60, calls=1)


def test_meter_record_accumulates_total():
    m = TokenMeter()
    m.record(UsageEnded(input_tokens=10, output_tokens=5, cached_input_tokens=2))
    m.record(UsageEnded(input_tokens=20, output_tokens=8, cached_input_tokens=0))
    assert m.total == TokenUsage(input_tokens=30, output_tokens=13,
                                 cached_input_tokens=2, calls=2)


def test_meter_record_attributes_per_label():
    m = TokenMeter()
    m.record(UsageEnded(input_tokens=10, output_tokens=5), label="planner")
    m.record(UsageEnded(input_tokens=4, output_tokens=2), label="planner")
    m.record(UsageEnded(input_tokens=7, output_tokens=1), label="implementer")
    assert m.by_node["planner"] == TokenUsage(input_tokens=14, output_tokens=7, calls=2)
    assert m.by_node["implementer"] == TokenUsage(input_tokens=7, output_tokens=1, calls=1)


def test_meter_record_without_label_only_totals():
    m = TokenMeter()
    m.record(UsageEnded(input_tokens=10, output_tokens=5))
    assert m.total.calls == 1
    assert m.by_node == {}


def test_meter_snapshot_is_plain_serializable_dict():
    m = TokenMeter()
    m.record(UsageEnded(input_tokens=10, output_tokens=5, cached_input_tokens=2),
             label="planner")
    snap = m.snapshot()
    assert snap["total"] == {"input_tokens": 10, "output_tokens": 5,
                             "cached_input_tokens": 2, "calls": 1}
    assert snap["by_node"]["planner"]["input_tokens"] == 10
    # round-trips through JSON unchanged
    import json
    assert json.loads(json.dumps(snap)) == snap
