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
