"""OllamaChat: native /api/chat protocol.

Covers body shape, OpenAI→Ollama message translation, and chunk → LLMEvent
parsing. The Agent's history stays OpenAI-shaped above this boundary; this
protocol does the translation.
"""
from __future__ import annotations

from poor_code.provider.events import (
    FinishedReason,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)
from poor_code.provider.protocols.ollama_chat import OllamaChat


def test_build_body_sets_stream_true_and_passes_messages():
    body = OllamaChat().build_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gpt-oss:120b",
    )
    assert body["model"] == "gpt-oss:120b"
    assert body["stream"] is True
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_build_body_passes_tools_when_present():
    tools = [
        {"type": "function", "function": {"name": "read", "description": "d", "parameters": {}}}
    ]
    body = OllamaChat().build_body(messages=[], tools=tools, model="m")
    assert body["tools"] == tools


def test_build_body_translates_openai_assistant_tool_calls_to_ollama_shape():
    """OpenAI: arguments is a JSON string + has id/type. Ollama: arguments is
    an object and there is no id/type."""
    body = OllamaChat().build_body(
        messages=[
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
            }
        ],
        tools=[],
        model="m",
    )
    assert body["messages"] == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read", "arguments": {"path": "a"}}}
            ],
        }
    ]


def test_build_body_drops_tool_call_id_from_tool_messages():
    body = OllamaChat().build_body(
        messages=[{"role": "tool", "tool_call_id": "call_1", "content": "result"}],
        tools=[],
        model="m",
    )
    assert body["messages"] == [{"role": "tool", "content": "result"}]


def test_parse_text_delta():
    parser = OllamaChat().for_stream()
    events = list(parser.parse_chunk({
        "message": {"role": "assistant", "content": "hi"},
        "done": False,
    }))
    assert events == [TextDelta(text="hi")]


def test_parse_done_emits_finished_reason():
    parser = OllamaChat().for_stream()
    events = list(parser.parse_chunk({
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "stop",
    }))
    assert events == [FinishedReason(reason="stop")]


def test_parse_tool_call_emits_started_input_delta_ended():
    """Ollama emits a complete tool call in one chunk (no token-level streaming
    of arguments). We still emit Started+InputDelta+Ended so the Agent's
    OpenAI-style consumer code keeps working."""
    parser = OllamaChat().for_stream()
    events = list(parser.parse_chunk({
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read", "arguments": {"path": "a"}}}
            ],
        },
        "done": False,
    }))
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["ToolCallStarted", "ToolCallInputDelta", "ToolCallEnded"]
    assert isinstance(events[0], ToolCallStarted)
    assert events[0].name == "read"
    cid = events[0].call_id
    assert events[1] == ToolCallInputDelta(call_id=cid, json_delta='{"path": "a"}')
    assert events[2] == ToolCallEnded(call_id=cid)


def test_parse_unknown_done_reason_falls_back_to_stop():
    parser = OllamaChat().for_stream()
    events = list(parser.parse_chunk({
        "message": {"content": ""},
        "done": True,
        "done_reason": "load",  # not in our Literal
    }))
    assert events == [FinishedReason(reason="stop")]


def test_for_stream_returns_fresh_parser():
    proto = OllamaChat()
    a = proto.for_stream()
    b = proto.for_stream()
    assert a is not b
