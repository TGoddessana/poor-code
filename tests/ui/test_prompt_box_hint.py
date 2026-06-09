from poor_code.ui.store import AppState, TurnView
from poor_code.ui.widgets.prompt_box import _placeholder_for


def test_paused_turn_shows_steering_hint():
    state = AppState(
        is_processing=False,
        turns=(TurnView(turn_id="t", cmd_id="c", user_text="x", status="paused"),),
    )
    assert "steer" in _placeholder_for(state).lower()


def test_processing_hint_mentions_esc():
    state = AppState(
        is_processing=True,
        turns=(TurnView(turn_id="t", cmd_id="c", user_text="x", status="running"),),
    )
    assert "esc" in _placeholder_for(state).lower()


def test_idle_returns_none():
    assert _placeholder_for(AppState()) is None
