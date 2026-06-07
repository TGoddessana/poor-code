"""Test that ExploringNode._stream_round does NOT leak raw text deltas to the sink,
while still accumulating them locally for parsing."""
import pytest

from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.provider.events import FinishedReason, TextDelta


class _Sink:
    def __init__(self):
        self.text = []

    def text_delta(self, t):
        self.text.append(t)

    def tool_started(self, *a, **k): ...
    def tool_finished(self, *a, **k): ...
    def tool_failed(self, *a, **k): ...


class _Tools:
    def schemas(self):
        return []


class _LLM:
    provider_name = "x"
    model = "m"

    async def stream(self, messages, tools):
        yield TextDelta(text="Let me grep for the slash handler...")
        yield FinishedReason(reason="stop")


@pytest.mark.asyncio
async def test_stream_round_does_not_leak_text_to_sink():
    node = ExploringNode.__new__(ExploringNode)
    node._llm = _LLM()
    node._tools = _Tools()
    node.name = "explorer"
    sink = _Sink()

    text, calls = await node._stream_round(
        [{"role": "user", "content": "hi"}], sink
    )

    # Accumulator must still contain the streamed text
    assert text == "Let me grep for the slash handler..."
    # Nothing must have leaked to the UI sink
    assert sink.text == []
