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
from poor_code.provider.framing import NdjsonFraming
from poor_code.provider.protocols.ollama_chat import OllamaChat
from poor_code.provider.route import Route


def _ndjson(chunks: list[dict]) -> bytes:
    return b"".join(json.dumps(c).encode() + b"\n" for c in chunks)


def _make_client() -> LLMClient:
    route = Route(
        protocol=OllamaChat(),
        endpoint="/api/chat",
        auth=BearerAuth(token="t"),
        framing=NdjsonFraming(),
    )
    return LLMClient(route=route, base_url="https://example.test", model="m")


@pytest.mark.asyncio
@respx.mock
async def test_stream_text_only():
    body = _ndjson([
        {"message": {"role": "assistant", "content": "hi"}, "done": False},
        {"message": {"role": "assistant", "content": " there"}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    ])
    respx.post("https://example.test/api/chat").mock(
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
            content=_ndjson([{"message": {"content": ""}, "done": True, "done_reason": "stop"}]),
        )

    route = Route(
        protocol=OllamaChat(),
        endpoint="/api/chat",
        auth=BearerAuth(token="sk-xyz"),
        framing=NdjsonFraming(),
    )
    client = LLMClient(route=route, base_url="https://example.test", model="m")
    respx.post("https://example.test/api/chat").mock(side_effect=_capture)
    [_ async for _ in client.stream(messages=[{"role": "user", "content": "x"}], tools=[])]

    assert captured["auth"] == "Bearer sk-xyz"
    assert captured["body"]["stream"] is True
    assert captured["body"]["model"] == "m"


@pytest.mark.asyncio
@respx.mock
async def test_stream_propagates_tool_call_events():
    body = _ndjson([
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "read", "arguments": {"path": "a"}}}
                ],
            },
            "done": False,
        },
        {"message": {"content": ""}, "done": True, "done_reason": "stop"},
    ])
    respx.post("https://example.test/api/chat").mock(
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
    respx.post("https://example.test/api/chat").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(httpx.HTTPStatusError):
        [_ async for _ in _make_client().stream(messages=[], tools=[])]


@pytest.mark.asyncio
@respx.mock
async def test_stream_http_error_includes_response_body_in_message():
    """A 404 with a real reason in the body must surface that text, not just
    the bare '404'. Otherwise the user sees a cryptic HTTPStatusError that
    hides the actual cause (model name typo, expired key, etc.)."""
    respx.post("https://example.test/api/chat").mock(
        return_value=httpx.Response(
            404,
            json={"error": "model 'nemotron3:33b' not found"},
        )
    )
    with pytest.raises(httpx.HTTPStatusError) as exc:
        [_ async for _ in _make_client().stream(messages=[], tools=[])]
    assert "model 'nemotron3:33b' not found" in str(exc.value)
    assert "404" in str(exc.value)
