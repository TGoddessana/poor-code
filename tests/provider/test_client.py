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
    ToolCallInputDelta,
    ToolCallStarted,
)
from poor_code.provider.framing import SseFraming
from poor_code.provider.protocols.openai_chat import OpenAICompatibleChat
from poor_code.provider.route import Route


def _sse(chunks: list[dict]) -> bytes:
    lines = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks)
    return lines + b"data: [DONE]\n\n"


def _make_client() -> LLMClient:
    route = Route(
        protocol=OpenAICompatibleChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="t"),
        framing=SseFraming(),
    )
    return LLMClient(route=route, base_url="https://example.test", model="m")


@pytest.mark.asyncio
@respx.mock
async def test_stream_text_only():
    body = _sse([
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": " there"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body)
    )
    events = [
        ev async for ev in _make_client().stream(
            messages=[{"role": "user", "content": "x"}], tools=[]
        )
    ]
    assert events == [
        TextDelta(text="hi"),
        TextDelta(text=" there"),
        FinishedReason(reason="stop"),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_stream_sends_auth_header_and_streaming_body():
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse([{"choices": [{"delta": {}, "finish_reason": "stop"}]}]),
        )

    route = Route(
        protocol=OpenAICompatibleChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="sk-xyz"),
        framing=SseFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")
    respx.post("https://example.test/v1/chat/completions").mock(side_effect=_capture)
    [_ async for _ in client.stream(messages=[{"role": "user", "content": "x"}], tools=[])]

    assert captured["auth"] == "Bearer sk-xyz"
    assert captured["body"]["stream"] is True
    assert captured["body"]["model"] == "m"


@pytest.mark.asyncio
@respx.mock
async def test_stream_propagates_tool_call_events():
    body = _sse([
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "read", "arguments": ""}}
        ]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"path":"a"}'}}
        ]}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body)
    )
    events = [ev async for ev in _make_client().stream(messages=[], tools=[])]
    kinds = [type(e).__name__ for e in events]
    assert "ToolCallStarted" in kinds
    assert "ToolCallInputDelta" in kinds
    assert "ToolCallEnded" in kinds
    assert isinstance(events[-1], FinishedReason)


@pytest.mark.asyncio
@respx.mock
async def test_stream_http_error_raises():
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(httpx.HTTPStatusError):
        [_ async for _ in _make_client().stream(messages=[], tools=[])]


@pytest.mark.asyncio
@respx.mock
async def test_stream_http_error_includes_response_body_in_message():
    """A 404 with a real reason in the body must surface that text."""
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            404,
            json={"error": "model 'nemotron3:33b' not found"},
        )
    )
    with pytest.raises(httpx.HTTPStatusError) as exc:
        [_ async for _ in _make_client().stream(messages=[], tools=[])]
    assert "model 'nemotron3:33b' not found" in str(exc.value)
    assert "404" in str(exc.value)
