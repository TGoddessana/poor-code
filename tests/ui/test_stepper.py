from poor_code.ui.store import AppState, NodeLabelSegment, TurnView
from poor_code.ui.widgets.stepper import render_stepper


def test_stepper_marks_current_and_seen():
    s = AppState(current_phase="planning", phases_seen=("routing", "locating", "planning"))
    line = render_stepper(s)
    assert "✓ Route" in line and "✓ Locate" in line
    assert "⟳ Plan" in line
    assert "· Build" in line and "· Done" in line


def test_stepper_unknown_phase_does_not_crash():
    s = AppState(current_phase="mystery", phases_seen=("mystery",))
    line = render_stepper(s)  # no exception, renders the 6 rail
    assert "Route" in line


def test_stepper_empty_when_no_phase():
    assert render_stepper(AppState()) == ""


def test_stepper_includes_current_node_detail():
    turn = TurnView(
        turn_id="T",
        cmd_id="c",
        user_text="fix",
        segments=(NodeLabelSegment(
            node="implementer",
            phase="implementing",
            activity="Writing code for t2",
        ),),
    )
    s = AppState(
        current_phase="implementing",
        phases_seen=("routing", "locating", "planning", "implementing"),
        turns=(turn,),
    )
    assert "│ Writing code for t2 · implementer" in render_stepper(s)
