"""OpenAICompatibleChat: OpenAI /v1/chat/completions streaming protocol."""
from __future__ import annotations

import json

from poor_code.provider.events import (
    FinishedReason,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)
from poor_code.provider.protocols.openai_chat import OpenAICompatibleChat


def test_build_body_passes_messages_unchanged():
    """메시지 변환 없음 — OpenAI 포맷 그대로 전달."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path":"a"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
    ]
    body = OpenAICompatibleChat().build_body(messages=messages, tools=[], model="m")
    assert body["messages"] == messages  # 변환 없음


def test_build_body_sets_stream_true():
    body = OpenAICompatibleChat().build_body(messages=[], tools=[], model="gpt-oss:120b")
    assert body["stream"] is True
    assert body["model"] == "gpt-oss:120b"


def test_build_body_includes_tools_when_present():
    tools = [{"type": "function", "function": {"name": "read", "description": "d", "parameters": {}}}]
    body = OpenAICompatibleChat().build_body(messages=[], tools=tools, model="m")
    assert body["tools"] == tools


def test_build_body_omits_tools_when_empty():
    body = OpenAICompatibleChat().build_body(messages=[], tools=[], model="m")
    assert "tools" not in body


def test_parse_text_delta():
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "choices": [{"delta": {"content": "hi"}, "finish_reason": None}]
    }))
    assert events == [TextDelta(text="hi")]


def test_parse_empty_content_yields_nothing():
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "choices": [{"delta": {"content": ""}, "finish_reason": None}]
    }))
    assert events == []


def test_parse_finish_reason_stop_without_tool_calls():
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "choices": [{"delta": {}, "finish_reason": "stop"}]
    }))
    assert events == [FinishedReason(reason="stop")]


def test_parse_finish_reason_length():
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "choices": [{"delta": {}, "finish_reason": "length"}]
    }))
    assert events == [FinishedReason(reason="length")]


def test_parse_unknown_finish_reason_falls_back_to_stop():
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({
        "choices": [{"delta": {}, "finish_reason": "content_filter"}]
    }))
    assert events == [FinishedReason(reason="stop")]


def test_parse_tool_calls_accumulated_and_emitted_on_finish():
    """OpenAI는 tool_call arguments를 여러 청크에 나눠 보냄.
    파서는 finish_reason 도달 시 Started+InputDelta+Ended를 한꺼번에 emit."""
    parser = OpenAICompatibleChat().for_stream()

    # 청크 1: tool call 시작 (id + name)
    list(parser.parse_chunk({
        "choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_abc", "type": "function",
             "function": {"name": "read", "arguments": ""}}
        ]}, "finish_reason": None}]
    }))

    # 청크 2: arguments 첫 번째 조각
    list(parser.parse_chunk({
        "choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"path":'}}
        ]}, "finish_reason": None}]
    }))

    # 청크 3: arguments 두 번째 조각
    list(parser.parse_chunk({
        "choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"a"}'}}
        ]}, "finish_reason": None}]
    }))

    # 청크 4: finish_reason → emit all
    events = list(parser.parse_chunk({
        "choices": [{"delta": {}, "finish_reason": "tool_calls"}]
    }))

    kinds = [type(e).__name__ for e in events]
    assert kinds == ["ToolCallStarted", "ToolCallInputDelta", "ToolCallEnded", "FinishedReason"]

    started = events[0]
    assert isinstance(started, ToolCallStarted)
    assert started.call_id == "call_abc"
    assert started.name == "read"

    input_delta = events[1]
    assert isinstance(input_delta, ToolCallInputDelta)
    assert input_delta.call_id == "call_abc"
    assert json.loads(input_delta.json_delta) == {"path": "a"}

    assert isinstance(events[2], ToolCallEnded)
    assert events[2].call_id == "call_abc"

    assert events[3] == FinishedReason(reason="tool_calls")


def test_parse_chunk_with_no_choices_yields_nothing():
    parser = OpenAICompatibleChat().for_stream()
    events = list(parser.parse_chunk({}))
    assert events == []


def test_for_stream_returns_fresh_parser():
    proto = OpenAICompatibleChat()
    assert proto.for_stream() is not proto.for_stream()


def test_parse_two_parallel_tool_calls():
    """Two tool calls with different indexes both accumulated and emitted."""
    parser = OpenAICompatibleChat().for_stream()

    list(parser.parse_chunk({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_0", "type": "function", "function": {"name": "read", "arguments": ""}},
        {"index": 1, "id": "call_1", "type": "function", "function": {"name": "write", "arguments": ""}},
    ]}, "finish_reason": None}]}))

    list(parser.parse_chunk({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '{"path":"a"}'}},
        {"index": 1, "function": {"arguments": '{"path":"b"}'}},
    ]}, "finish_reason": None}]}))

    events = list(parser.parse_chunk({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}))

    kinds = [type(e).__name__ for e in events]
    # call_0 then call_1 (sorted by index), then FinishedReason
    assert kinds == [
        "ToolCallStarted", "ToolCallInputDelta", "ToolCallEnded",
        "ToolCallStarted", "ToolCallInputDelta", "ToolCallEnded",
        "FinishedReason",
    ]
    assert events[0].call_id == "call_0"
    assert events[0].name == "read"
    assert events[3].call_id == "call_1"
    assert events[3].name == "write"
