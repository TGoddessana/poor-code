import json

import httpx
import pytest
import respx

from poor_code.provider.auth import BearerAuth
from poor_code.provider.client import LLMClient
from poor_code.provider.events import (
    FinishedReason,
    TextDelta,
    ToolCallEnded,
    ToolCallStarted,
)
from poor_code.provider.framing import SseFraming
from poor_code.provider.protocols.openai_chat import OpenAIChat
from poor_code.provider.route import Route


def _sse(chunks: list[dict]) -> bytes:
    out = b""
    for c in chunks:
        out += b"data: " + json.dumps(c).encode() + b"\n\n"
    out += b"data: [DONE]\n\n"
    return out


@pytest.mark.asyncio
@respx.mock
async def test_stream_text_only():
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="t"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")

    body = _sse([
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": " there"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body)
    )

    events = [
        ev async for ev in client.stream(messages=[{"role": "user", "content": "x"}], tools=[])
    ]
    assert events == [
        TextDelta(text="hi"),
        TextDelta(text=" there"),
        FinishedReason(reason="stop"),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_stream_sends_auth_header_and_streaming_body():
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="sk-xyz"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse([{"choices": [{"delta": {}, "finish_reason": "stop"}]}]),
        )

    respx.post("https://example.test/v1/chat/completions").mock(side_effect=_capture)
    [_ async for _ in client.stream(messages=[{"role": "user", "content": "x"}], tools=[])]

    assert captured["auth"] == "Bearer sk-xyz"
    assert captured["body"]["stream"] is True
    assert captured["body"]["model"] == "m"


@pytest.mark.asyncio
@respx.mock
async def test_stream_propagates_tool_call_events():
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="t"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")

    body = _sse([
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "read", "arguments": ""}}
        ]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"path":"a"}'}}
        ]}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body)
    )

    events = [ev async for ev in client.stream(messages=[], tools=[])]
    kinds = [type(e).__name__ for e in events]
    assert "ToolCallStarted" in kinds
    assert "ToolCallEnded" in kinds
    assert events[-1] == FinishedReason(reason="tool_calls")


@pytest.mark.asyncio
@respx.mock
async def test_stream_http_error_raises():
    route = Route(
        protocol=OpenAIChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="t"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(httpx.HTTPStatusError):
        [_ async for _ in client.stream(messages=[], tools=[])]
