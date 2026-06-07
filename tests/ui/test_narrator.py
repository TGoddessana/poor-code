from poor_code.domain.session.models import (
    CodeContext, CodeRef, GroundingStatus, Phase, Plan, SessionState, Cursor, Request, RequestKind,
)
from poor_code.domain.harness.node import NodeResult
from poor_code.ui.narrator import StaticNarrator


def _state(repair_hint=None):
    return SessionState(
        cursor=Cursor(phase=Phase.PLANNING, current_node="planner"),
        request=Request(raw_text="add /status", kind=RequestKind.ENGINEERING),
        repair_hint=repair_hint,
    )


def test_activity_known_node_present_tense():
    n = StaticNarrator()
    assert n.activity("explorer", Phase.LOCATING, _state()) == "Exploring the codebase"
    assert "clarif" in n.activity("interviewer", Phase.INTERVIEWING, _state()).lower()


def test_activity_unknown_node_phase_fallback_no_crash():
    n = StaticNarrator()
    out = n.activity("totally_new_step", Phase.PLANNING, _state())
    assert isinstance(out, str) and out


def test_activity_planner_reentry_uses_repair_hint():
    n = StaticNarrator()
    out = n.activity("planner", Phase.PLANNING, _state(repair_hint="task2 outside edit scope"))
    assert "Revising" in out and "task2 outside edit scope" in out


def test_summary_explorer_counts_codecontext():
    n = StaticNarrator()
    cc = CodeContext(
        candidates=(CodeRef(file="a.py"), CodeRef(file="b.py")),
        related_tests=(CodeRef(file="t.py"),),
        grounding=GroundingStatus.NOT_FOUND,
    )
    headline, detail = n.summary("explorer", NodeResult(output=cc))
    assert "2 files" in headline and "1 test" in headline
    assert any("a.py" in d for d in detail)


def test_summary_unknown_node_empty_no_card():
    n = StaticNarrator()
    assert n.summary("totally_new_step", NodeResult(output=None)) == ("", ())
