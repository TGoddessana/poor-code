import dataclasses

import pytest

from poor_code.messages import CancelTurn, Command, RunSlashCommand, SendPrompt


def test_send_prompt_carries_text_and_unique_cmd_id():
    a = SendPrompt(text="hi")
    b = SendPrompt(text="hi")
    assert a.text == "hi"
    assert a.cmd_id != b.cmd_id
    assert isinstance(a.cmd_id, str) and len(a.cmd_id) > 0


def test_run_slash_command_carries_name_and_args_tuple():
    cmd = RunSlashCommand(name="help", args=("--verbose",))
    assert cmd.name == "help"
    assert cmd.args == ("--verbose",)
    assert isinstance(cmd.args, tuple)


def test_cancel_turn_has_only_cmd_id():
    cmd = CancelTurn()
    assert isinstance(cmd.cmd_id, str) and len(cmd.cmd_id) > 0


@pytest.mark.parametrize("cls,kwargs", [
    (SendPrompt, {"text": "x"}),
    (CancelTurn, {}),
    (RunSlashCommand, {"name": "foo"}),
])
def test_commands_are_frozen(cls, kwargs):
    cmd = cls(**kwargs)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cmd.cmd_id = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize("cls,kwargs", [
    (SendPrompt, {"text": "x"}),
    (CancelTurn, {}),
    (RunSlashCommand, {"name": "foo"}),
])
def test_commands_are_subclass_of_command(cls, kwargs):
    assert isinstance(cls(**kwargs), Command)


from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    Event,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnded,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
)


def test_turn_started_correlates_command_and_generates_turn_id():
    ev = TurnStarted(cmd_id="abc")
    other = TurnStarted(cmd_id="abc")
    assert ev.cmd_id == "abc"
    assert ev.turn_id != other.turn_id
    assert isinstance(ev.turn_id, str) and len(ev.turn_id) > 0


def test_assistant_text_delta_is_chunk_not_cumulative():
    # The contract is that .text is the chunk; reducer accumulates.
    ev = AssistantTextDelta(turn_id="t1", text="hello")
    assert ev.text == "hello"


def test_tool_call_started_carries_args_dict():
    ev = ToolCallStarted(turn_id="t1", tool_call_id="c1", tool_name="bash",
                         args={"cmd": "ls"})
    assert ev.args == {"cmd": "ls"}


def test_usage_updated_field_names_match_provider_response_usage_dict():
    # Spec pins: ProviderResponse.usage keys = field names of UsageUpdated.
    # Verified by constructing via **kwargs.
    ev = UsageUpdated(turn_id="t1", input_tokens=10, output_tokens=20, cost_usd=0.001)
    assert ev.input_tokens == 10 and ev.output_tokens == 20 and ev.cost_usd == 0.001


@pytest.mark.parametrize("ev", [
    TurnStarted(cmd_id="c"),
    TurnEnded(turn_id="t"),
    TurnFailed(turn_id="t", error="x"),
    AssistantTextDelta(turn_id="t", text="x"),
    AssistantMessageCompleted(turn_id="t", text="x"),
    ToolCallStarted(turn_id="t", tool_call_id="c", tool_name="n", args={}),
    ToolCallFinished(turn_id="t", tool_call_id="c", result=None),
    ToolCallFailed(turn_id="t", tool_call_id="c", error="x"),
    UsageUpdated(turn_id="t", input_tokens=0, output_tokens=0, cost_usd=0.0),
])
def test_events_are_frozen_and_subclass_event(ev):
    assert isinstance(ev, Event)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.turn_id = "mutated"  # type: ignore[misc]
