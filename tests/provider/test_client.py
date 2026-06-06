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


def _route() -> Route:
    return Route(
        protocol=OpenAICompatibleChat(),
        endpoint="/v1/chat/completions",
        auth=BearerAuth(token="t"),
        framing=SseFraming(),
    )


def _make_client(**kwargs) -> LLMClient:
    return LLMClient(route=_route(), base_url="https://example.test", model="m", **kwargs)


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


# --- per-call TOTAL wall-clock budget (FM3) ------------------------------------

def test_call_timeout_default_is_finite_positive():
    """A total wall-clock budget per call must exist by default — the idle timeout
    only catches single gaps, so accumulated sub-idle gaps could run to 1800s."""
    from poor_code.provider.client import DEFAULT_CALL_TIMEOUT
    assert DEFAULT_CALL_TIMEOUT is not None and DEFAULT_CALL_TIMEOUT > 0
    assert _make_client()._call_timeout == DEFAULT_CALL_TIMEOUT


@pytest.mark.asyncio
@respx.mock
async def test_stream_raises_when_call_exceeds_wall_clock_budget():
    """Many sub-idle chunks accumulating past the budget must trip a timeout, not
    run forever. A fake monotonic clock makes this deterministic."""
    from poor_code.provider.client import LLMCallTimeout
    body = _sse([
        {"choices": [{"delta": {"content": "a"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "b"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "c"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body))
    client = _make_client(call_timeout=100.0)
    ticks = iter([0.0, 10.0, 200.0, 300.0, 400.0])  # 3rd chunk is past the 100s budget
    client._monotonic = lambda: next(ticks)
    collected = []
    with pytest.raises(LLMCallTimeout):
        async for ev in client.stream(messages=[], tools=[]):
            collected.append(ev)
    assert TextDelta(text="a") in collected  # earlier chunks streamed before the trip


@pytest.mark.asyncio
@respx.mock
async def test_call_timeout_is_not_retried():
    """The budget cap is not a transport stall — retrying would burn it again."""
    from poor_code.provider.client import LLMCallTimeout
    body = _sse([
        {"choices": [{"delta": {"content": "a"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    route = respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body))
    client = _make_client(call_timeout=50.0, max_retries=2)
    ticks = iter([0.0, 999.0, 999.0, 999.0])
    client._monotonic = lambda: next(ticks)
    with pytest.raises(LLMCallTimeout):
        [_ async for _ in client.stream(messages=[], tools=[])]
    assert route.call_count == 1


def test_idle_read_timeout_is_finite():
    """read=None turns a provider stall into an infinite hang. The read (idle)
    timeout must be a finite, positive number so a stalled stream raises."""
    t = _make_client()._timeout
    assert t.read is not None and t.read > 0
    assert t.connect is not None and t.connect > 0


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_transport_stall_before_first_event():
    """A stall before any token arrives is retried with a fresh request."""
    body = _sse([
        {"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    route = respx.post("https://example.test/v1/chat/completions").mock(
        side_effect=[httpx.ReadTimeout("stall"), httpx.Response(200, content=body)]
    )
    events = [ev async for ev in _make_client().stream(messages=[], tools=[])]
    assert route.call_count == 2                     # first attempt stalled, retry succeeded
    assert TextDelta(text="ok") in events
    assert isinstance(events[-1], FinishedReason)


@pytest.mark.asyncio
@respx.mock
async def test_gives_up_after_max_retries_on_persistent_stall():
    route = respx.post("https://example.test/v1/chat/completions").mock(
        side_effect=httpx.ReadTimeout("stall")
    )
    client = _make_client(max_retries=2)
    with pytest.raises(httpx.TimeoutException):
        [_ async for _ in client.stream(messages=[], tools=[])]
    assert route.call_count == 3                      # 1 initial + 2 retries


@pytest.mark.asyncio
@respx.mock
async def test_stream_records_usage_into_meter():
    """Every completed stream's token usage funnels into the client's meter — the
    single accounting point the harness reads for results.json (was always 0)."""
    body = _sse([
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 200, "completion_tokens": 30,
                                  "prompt_tokens_details": {"cached_tokens": 150}}},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body))
    client = _make_client()
    [_ async for _ in client.stream(messages=[], tools=[])]
    assert client.meter.total.input_tokens == 200
    assert client.meter.total.output_tokens == 30
    assert client.meter.total.cached_input_tokens == 150
    assert client.meter.total.calls == 1


@pytest.mark.asyncio
@respx.mock
async def test_stream_attributes_usage_to_active_label():
    """When a node tags the client with its name, usage is attributed per-node so
    the harness can see WHERE tokens (and context bloat) go."""
    body = _sse([
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 10}},
    ])
    respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=body))
    client = _make_client()
    client.active_label = "planner"
    [_ async for _ in client.stream(messages=[], tools=[])]
    assert client.meter.by_node["planner"].input_tokens == 50


@pytest.mark.asyncio
@respx.mock
async def test_http_status_error_is_not_retried():
    """A 5xx is a definite answer, not a transport stall — do not retry it."""
    route = respx.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(httpx.HTTPStatusError):
        [_ async for _ in _make_client(max_retries=2).stream(messages=[], tools=[])]
    assert route.call_count == 1
