import dataclasses

import pytest

from poor_code.ui.store import AppState, ToolCallView, TurnView, UsageState


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
