from poor_code.domain.session.models import (
    ChecksObserved,
    CodeContext,
    CodeRef,
    Cursor,
    FeedbackEntry,
    GroundingStatus,
    Layer,
    Phase,
    Plan,
    Request,
    RequestKind,
    SessionState,
    Task,
    ValidationResult,
    Verdict,
    VerdictKind,
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


def test_summary_explorer_labels_symbols_and_dedups_and_hides_grounding():
    n = StaticNarrator()
    cc = CodeContext(
        candidates=(
            CodeRef(file="prompt_box.py", symbol="PromptBox"),
            CodeRef(file="prompt_box.py", symbol="compose"),
            CodeRef(file="prompt_box.py", symbol="PromptBox"),   # dup of the first label
        ),
        grounding=GroundingStatus.NOT_FOUND,
    )
    headline, detail = n.summary("explorer", NodeResult(output=cc))
    # 1 unique file; grounding NOT shown because candidates exist (gate advanced on them)
    assert "1 file" in headline
    assert "grounding" not in headline
    # labels are file::symbol and de-duped (no repeated "prompt_box.py" rows)
    assert detail == ("prompt_box.py::PromptBox", "prompt_box.py::compose")


def test_summary_explorer_shows_grounding_only_when_no_candidates():
    n = StaticNarrator()
    cc = CodeContext(candidates=(), grounding=GroundingStatus.NOT_FOUND)
    headline, detail = n.summary("explorer", NodeResult(output=cc))
    assert "grounding: not_found" in headline
    assert detail == ()


def test_activity_names_current_inner_task():
    n = StaticNarrator()
    state = SessionState(
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"),
        plan=Plan(tasks=(Task(id="t2", title="Wire TUI", purpose="p"),)),
    )
    assert n.activity("implementer", Phase.IMPLEMENTING, state) == "Writing code for t2: Wire TUI"


def test_summary_validation_runner_surfaces_command_and_output():
    n = StaticNarrator()
    result = ValidationResult(
        command="pytest tests/ui",
        exit_code=1,
        passed=False,
        output="FAILED test_x",
    )
    headline, detail = n.summary("validation_runner", NodeResult(output=result))
    assert headline == "Validation failed (exit 1)"
    assert detail == ("pytest tests/ui", "FAILED test_x")


def test_summary_validator_and_failure_analyst_are_visible():
    n = StaticNarrator()
    checks = ChecksObserved(results=(("acceptance", True), ("regression", False)))
    headline, detail = n.summary("validator", NodeResult(output=checks))
    assert headline == "Validator observed 1/2 checks passing"
    assert "regression: FAIL" in detail

    feedback = FeedbackEntry(
        failure_type="test_failure",
        symptom="pytest failed",
        prevention_hint="Run the focused test first",
    )
    headline, detail = n.summary("failure_analyst", NodeResult(output=feedback))
    assert headline == "Failure lesson: test_failure"
    assert detail == ("pytest failed", "Run the focused test first")


def test_summary_verdict_only_nodes_get_result_cards():
    n = StaticNarrator()
    verdict = Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint="split task t2")
    headline, detail = n.summary("plan_reviewer", NodeResult(verdict=verdict))
    assert headline == "plan_reviewer requested repair (plan)"
    assert detail == ("split task t2",)


def test_summary_unknown_node_empty_no_card():
    n = StaticNarrator()
    assert n.summary("totally_new_step", NodeResult(output=None)) == ("", ())
