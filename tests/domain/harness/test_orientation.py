from poor_code.domain.harness.orientation import render_position
from poor_code.domain.session.models import (
    CodeContext, Cursor, GroundingStatus, Phase, Plan, Request, RequestKind,
    Requirement, SessionState, Task, TaskStatus,
)


def _planning_state():
    return SessionState(
        request=Request(raw_text="build it", kind=RequestKind.ENGINEERING),
        understanding=CodeContext(candidates=(), grounding=GroundingStatus.GREENFIELD),
        requirement=Requirement(summary="s", acceptance=("a", "b")),
    )


def test_planner_position_marks_current_and_done():
    out = render_position("planner", _planning_state())
    assert "you are the Planner" in out
    assert "[PLAN ▶]" in out
    assert "explore ✓" in out
    assert "interview ✓" in out
    assert "located (greenfield)" in out
    assert "requirement set (2 acceptance)" in out
    assert "PlanGate checks your plan" in out


def test_explorer_position_nothing_done_yet():
    state = SessionState(request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    out = render_position("explorer", state)
    assert "[EXPLORE ▶]" in out
    assert "✓" not in out               # nothing completed
    assert "Interviewer turns your findings" in out


def test_implementer_position_shows_task_progress():
    state = SessionState(
        request=Request(raw_text="x", kind=RequestKind.ENGINEERING),
        requirement=Requirement(summary="s"),
        plan=Plan(tasks=(
            Task(id="t1", title="A", purpose="", status=TaskStatus.DONE),
            Task(id="t2", title="server.js", purpose=""),
            Task(id="t3", title="C", purpose=""),
        )),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"),
    )
    out = render_position("implementer", state)
    assert "[IMPLEMENT ▶]" in out
    assert "plan has 3 tasks" in out
    assert "done: t1" in out
    assert 'doing: t2 "server.js"' in out
    assert "left: t3" in out
    assert "ValidationRunner runs your VALIDATION" in out


def test_located_with_candidates_counts_them():
    state = SessionState(
        request=Request(raw_text="x", kind=RequestKind.ENGINEERING),
        understanding=CodeContext(candidates=(), grounding=GroundingStatus.NOT_FOUND),
    )
    # no candidates, not_found → shows grounding label, not a count
    assert "located (not_found)" in render_position("interviewer", state)
