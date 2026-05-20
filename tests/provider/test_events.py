from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)


def test_text_delta_is_llm_event():
    ev = TextDelta(text="hi")
    assert isinstance(ev, LLMEvent)
    assert ev.text == "hi"


def test_tool_call_started_carries_id_and_name():
    ev = ToolCallStarted(call_id="c1", name="read")
    assert ev.call_id == "c1"
    assert ev.name == "read"


def test_tool_call_input_delta_carries_partial_json():
    ev = ToolCallInputDelta(call_id="c1", json_delta='{"pa')
    assert ev.json_delta == '{"pa'


def test_finished_reason_values():
    for r in ("stop", "tool_calls", "length", "error"):
        ev = FinishedReason(reason=r)
        assert ev.reason == r


def test_tool_call_ended_carries_id():
    assert ToolCallEnded(call_id="c1").call_id == "c1"
