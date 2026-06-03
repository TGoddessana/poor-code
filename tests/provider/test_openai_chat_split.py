from poor_code.provider.protocols.openai_chat import OpenAICompatibleChat
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


def _delta_chunk(args: str, name="read", idx=0, cid="c1"):
    return {"choices": [{"delta": {"tool_calls": [
        {"index": idx, "id": cid, "function": {"name": name, "arguments": args}}
    ]}}]}


def _finish_chunk():
    return {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}


def test_concatenated_args_emitted_verbatim_not_split():
    # The defensive split (one call's args crammed with N objects → N calls) was
    # removed: the parser now emits one call's accumulated args verbatim. A model
    # that produces malformed args is caught downstream by schema validation +
    # the dispatch re-roll, not silently repaired here.
    p = OpenAICompatibleChat().for_stream()
    list(p.parse_chunk(_delta_chunk('{"path":"a"}{"path":"b"}{"path":"c"}')))
    events = list(p.parse_chunk(_finish_chunk()))
    starts = [e for e in events if isinstance(e, ToolCallStarted)]
    deltas = [e for e in events if isinstance(e, ToolCallInputDelta)]
    assert [s.call_id for s in starts] == ["c1"]            # single call, no #suffix
    assert [d.json_delta for d in deltas] == ['{"path":"a"}{"path":"b"}{"path":"c"}']
    assert sum(isinstance(e, ToolCallEnded) for e in events) == 1
    assert any(isinstance(e, FinishedReason) for e in events)


def test_single_call_unchanged():
    p = OpenAICompatibleChat().for_stream()
    list(p.parse_chunk(_delta_chunk('{"path":"a"}')))
    events = list(p.parse_chunk(_finish_chunk()))
    starts = [e for e in events if isinstance(e, ToolCallStarted)]
    deltas = [e for e in events if isinstance(e, ToolCallInputDelta)]
    assert len(starts) == 1 and starts[0].call_id == "c1"  # no #suffix
    assert deltas[0].json_delta == '{"path":"a"}'
