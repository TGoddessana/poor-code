import dataclasses
from dataclasses import dataclass

import pytest

from poor_code.ui.store import Action, AppState, ToolCallView, TurnView, UIAction, UsageState, reduce


def test_app_state_defaults():
    s = AppState()
    assert s.turns == ()
    assert s.is_processing is False
    assert s.usage == UsageState()
    assert s.last_error is None
    assert s.cwd == ""


def test_turn_view_defaults():
    t = TurnView(turn_id=None, cmd_id="c1", user_text="hi")
    assert t.turn_id is None
    assert t.assistant_text == ""
    assert t.tool_calls == ()
    assert t.status == "pending"
    assert t.error is None


def test_tool_call_view_required_fields():
    tc = ToolCallView(
        tool_call_id="tc1", tool_name="bash",
        args={"cmd": "ls"}, status="running",
    )
    assert tc.result is None and tc.error is None


def test_view_dataclasses_are_frozen():
    s = AppState()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.is_processing = True  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        UsageState().input_tokens = 5  # type: ignore[misc]


def test_reducer_returns_same_state_for_unknown_action():
    @dataclass(frozen=True)
    class _Unknown(UIAction):
        pass

    s = AppState(cwd="/x")
    out = reduce(s, _Unknown())  # type: ignore[arg-type]
    assert out is s  # identity, not just equality


from poor_code.messages import TurnEnded, TurnFailed, TurnStarted
from poor_code.ui.store import PromptSubmitted


def test_prompt_submitted_appends_pending_turn_and_sets_processing():
    s = AppState()
    s2 = reduce(s, PromptSubmitted(cmd_id="c1", user_text="hi"))
    assert len(s2.turns) == 1
    t = s2.turns[0]
    assert t.cmd_id == "c1" and t.user_text == "hi"
    assert t.turn_id is None and t.status == "pending"
    assert s2.is_processing is True


def test_turn_started_promotes_pending_turn_with_turn_id_and_running_status():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c1", user_text="hi"))
    s = reduce(s, TurnStarted(cmd_id="c1", turn_id="T1"))
    assert s.turns[0].turn_id == "T1"
    assert s.turns[0].status == "running"


def test_turn_started_with_unknown_cmd_id_is_noop():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c1", user_text="hi"))
    out = reduce(s, TurnStarted(cmd_id="UNKNOWN", turn_id="T1"))
    assert out is s


def test_turn_ended_marks_done_and_clears_processing():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c1", user_text="hi"))
    s = reduce(s, TurnStarted(cmd_id="c1", turn_id="T1"))
    s = reduce(s, TurnEnded(turn_id="T1"))
    assert s.turns[0].status == "done"
    assert s.is_processing is False


def test_turn_failed_marks_failed_clears_processing_records_last_error():
    s = reduce(AppState(), PromptSubmitted(cmd_id="c1", user_text="hi"))
    s = reduce(s, TurnStarted(cmd_id="c1", turn_id="T1"))
    s = reduce(s, TurnFailed(turn_id="T1", error="boom"))
    assert s.turns[0].status == "failed"
    assert s.turns[0].error == "boom"
    assert s.last_error == "boom"
    assert s.is_processing is False


from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    UsageUpdated,
)
from poor_code.ui.store import CwdChanged


def _running_state(turn_id: str = "T1", cmd_id: str = "c1") -> AppState:
    s = reduce(AppState(), PromptSubmitted(cmd_id=cmd_id, user_text="hi"))
    return reduce(s, TurnStarted(cmd_id=cmd_id, turn_id=turn_id))


def test_assistant_text_delta_accumulates():
    s = _running_state()
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="hel"))
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="lo"))
    assert s.turns[0].assistant_text == "hello"


def test_assistant_message_completed_replaces_assistant_text():
    s = _running_state()
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="partial"))
    s = reduce(s, AssistantMessageCompleted(turn_id="T1", text="final answer"))
    assert s.turns[0].assistant_text == "final answer"


from poor_code.ui.store import TextSegment


def test_segments_track_chronological_order_of_text_and_tools():
    """Iter 1: thinking text → tool. Iter 2: final answer. Segments must
    preserve that order so the UI can render thinking ABOVE the tool call
    and the final answer BELOW it."""
    s = _running_state()
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="Let me check..."))
    s = reduce(s, ToolCallStarted(
        turn_id="T1", tool_call_id="tc1", tool_name="read", args={"path": "a"}
    ))
    s = reduce(s, ToolCallFinished(turn_id="T1", tool_call_id="tc1", result="ok"))
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="The answer is X."))
    s = reduce(s, AssistantMessageCompleted(turn_id="T1", text="The answer is X."))

    segs = s.turns[0].segments
    assert len(segs) == 3
    assert isinstance(segs[0], TextSegment) and segs[0].text == "Let me check..."
    assert isinstance(segs[1], ToolCallView) and segs[1].status == "done"
    assert isinstance(segs[2], TextSegment) and segs[2].text == "The answer is X."


def test_text_delta_after_tool_starts_new_segment_not_appended_to_prior_text():
    s = _running_state()
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="hello"))
    s = reduce(s, ToolCallStarted(
        turn_id="T1", tool_call_id="tc1", tool_name="read", args={}
    ))
    s = reduce(s, AssistantTextDelta(turn_id="T1", text="world"))
    segs = s.turns[0].segments
    assert [type(x).__name__ for x in segs] == ["TextSegment", "ToolCallView", "TextSegment"]
    assert segs[0].text == "hello"
    assert segs[2].text == "world"


def test_tool_call_started_appends_running_tool_call():
    s = _running_state()
    s = reduce(s, ToolCallStarted(
        turn_id="T1", tool_call_id="tc1", tool_name="bash", args={"cmd": "ls"}
    ))
    tc = s.turns[0].tool_calls[0]
    assert tc.tool_call_id == "tc1" and tc.tool_name == "bash"
    assert tc.args == {"cmd": "ls"} and tc.status == "running"


def test_tool_call_finished_updates_status_and_result():
    s = _running_state()
    s = reduce(s, ToolCallStarted(
        turn_id="T1", tool_call_id="tc1", tool_name="bash", args={}
    ))
    s = reduce(s, ToolCallFinished(turn_id="T1", tool_call_id="tc1", result="ok"))
    tc = s.turns[0].tool_calls[0]
    assert tc.status == "done" and tc.result == "ok"


def test_tool_call_failed_updates_status_and_error():
    s = _running_state()
    s = reduce(s, ToolCallStarted(
        turn_id="T1", tool_call_id="tc1", tool_name="bash", args={}
    ))
    s = reduce(s, ToolCallFailed(turn_id="T1", tool_call_id="tc1", error="bad"))
    tc = s.turns[0].tool_calls[0]
    assert tc.status == "failed" and tc.error == "bad"


def test_usage_updated_accumulates():
    s = _running_state()
    s = reduce(s, UsageUpdated(turn_id="T1",
                               input_tokens=10, output_tokens=20, cost_usd=0.5))
    s = reduce(s, UsageUpdated(turn_id="T1",
                               input_tokens=5, output_tokens=5, cost_usd=0.25))
    assert s.usage.input_tokens == 15
    assert s.usage.output_tokens == 25
    assert s.usage.cost_usd == 0.75


def test_cwd_changed_updates_cwd_only():
    s = AppState(cwd="/old")
    s2 = reduce(s, CwdChanged(cwd="/new"))
    assert s2.cwd == "/new"
    assert s2.turns == s.turns  # untouched


from poor_code.ui.store import Store


def test_store_starts_with_initial_state():
    init = AppState(cwd="/x")
    assert Store(init).state is init


def test_store_dispatch_runs_reducer_and_updates_state():
    s = Store(AppState())
    s.dispatch(PromptSubmitted(cmd_id="c1", user_text="hi"))
    assert s.state.is_processing is True
    assert len(s.state.turns) == 1


def test_store_subscribe_fires_on_state_change():
    s = Store(AppState())
    seen: list[AppState] = []
    s.subscribe(seen.append)
    s.dispatch(PromptSubmitted(cmd_id="c1", user_text="hi"))
    assert len(seen) == 1
    assert seen[0] is s.state


def test_store_subscribe_does_not_fire_when_state_unchanged():
    @dataclass(frozen=True)
    class _NoOp(UIAction):
        pass

    s = Store(AppState())
    seen: list[AppState] = []
    s.subscribe(seen.append)
    s.dispatch(_NoOp())  # type: ignore[arg-type]
    assert seen == []


def test_store_unsubscribe_stops_callbacks():
    s = Store(AppState())
    seen: list[AppState] = []
    unsub = s.subscribe(seen.append)
    unsub()
    s.dispatch(PromptSubmitted(cmd_id="c1", user_text="hi"))
    assert seen == []


from poor_code.ui.store import ProviderChanged


def test_app_state_has_provider_and_model_defaults():
    s = AppState()
    assert s.provider_name is None
    assert s.model is None


def test_provider_changed_sets_fields():
    s = AppState()
    s2 = reduce(s, ProviderChanged(provider_name="ollama cloud", model="gpt-oss:120b"))
    assert s2.provider_name == "ollama cloud"
    assert s2.model == "gpt-oss:120b"


def test_provider_changed_to_none_clears_fields():
    s = AppState(provider_name="x", model="y")
    s2 = reduce(s, ProviderChanged(provider_name=None, model=None))
    assert s2.provider_name is None
    assert s2.model is None
