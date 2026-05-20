from poor_code.provider.protocols.openai_chat import OpenAIChat


def test_build_body_minimal():
    proto = OpenAIChat()
    body = proto.build_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="qwen2.5-coder:7b",
    )
    assert body == {
        "model": "qwen2.5-coder:7b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }


def test_build_body_with_tools_includes_tools_key():
    proto = OpenAIChat()
    tools_schema = [
        {
            "type": "function",
            "function": {"name": "read", "description": "d", "parameters": {}},
        }
    ]
    body = proto.build_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=tools_schema,
        model="m",
    )
    assert body["tools"] == tools_schema


def test_build_body_omits_tools_when_empty():
    proto = OpenAIChat()
    body = proto.build_body(messages=[], tools=[], model="m")
    assert "tools" not in body


def test_parse_text_delta():
    proto = OpenAIChat()
    events = list(
        proto.parse_chunk(
            {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
        )
    )
    from poor_code.provider.events import TextDelta
    assert events == [TextDelta(text="hi")]


def test_parse_tool_call_start_emits_started_then_input_delta():
    proto = OpenAIChat()
    events = list(
        proto.parse_chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "read", "arguments": ""},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
        )
    )
    from poor_code.provider.events import ToolCallStarted
    assert events == [ToolCallStarted(call_id="call_1", name="read")]


def test_parse_tool_call_argument_delta():
    proto = OpenAIChat()
    # First chunk registers the call so parser knows index→call_id.
    list(proto.parse_chunk({
        "choices": [{
            "delta": {"tool_calls": [{
                "index": 0, "id": "call_1",
                "function": {"name": "read", "arguments": ""},
            }]},
            "finish_reason": None,
        }]
    }))
    events = list(proto.parse_chunk({
        "choices": [{
            "delta": {"tool_calls": [{
                "index": 0,
                "function": {"arguments": '{"path":"a"}'},
            }]},
            "finish_reason": None,
        }]
    }))
    from poor_code.provider.events import ToolCallInputDelta
    assert events == [ToolCallInputDelta(call_id="call_1", json_delta='{"path":"a"}')]


def test_parse_finish_emits_ended_for_open_calls_then_finished_reason():
    proto = OpenAIChat()
    list(proto.parse_chunk({
        "choices": [{
            "delta": {"tool_calls": [{
                "index": 0, "id": "call_1",
                "function": {"name": "read", "arguments": ""},
            }]},
            "finish_reason": None,
        }]
    }))
    events = list(proto.parse_chunk({
        "choices": [{"delta": {}, "finish_reason": "tool_calls"}]
    }))
    from poor_code.provider.events import FinishedReason, ToolCallEnded
    assert events == [
        ToolCallEnded(call_id="call_1"),
        FinishedReason(reason="tool_calls"),
    ]


def test_parse_finish_stop_with_no_open_calls():
    proto = OpenAIChat()
    events = list(proto.parse_chunk(
        {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    ))
    from poor_code.provider.events import FinishedReason
    assert events == [FinishedReason(reason="stop")]
