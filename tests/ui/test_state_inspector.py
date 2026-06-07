from poor_code.ui.store import (
    AppState, TurnView, NodeResultSegment, PlanSegment,
)
from poor_code.ui.screens.state_inspector import render_inspector


def test_inspector_summarizes_appstate():
    turn = TurnView(
        turn_id="t1", cmd_id="c", user_text="add /status", status="running",
        segments=(
            NodeResultSegment(node="explorer", phase="locating", headline="Found 5 files"),
            PlanSegment(lines=("1. x", "2. y")),
        ),
    )
    s = AppState(turns=(turn,), current_phase="planning")
    text = render_inspector(s)
    assert "add /status" in text          # request
    assert "planning" in text             # phase
    assert "Found 5 files" in text        # latest node result
    assert "2" in text                     # plan task count


def test_inspector_empty_state():
    text = render_inspector(AppState())
    assert "No active work" in text  # graceful empty
