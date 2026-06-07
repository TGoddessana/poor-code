"""StaticNarrator — deterministic, zero-token narration (English; the OSS
first-class language).

activity() = a present-tense sentence per node (static map + repair_hint
slot-filling). summary() = a headline derived from the node's already-produced
structured output (counts on CodeContext/Plan). Unknown nodes fall back to a
phase sentence (activity) or an empty card (summary). ui->domain imports are
allowed; this reads domain models to count. Replaceable by an LLM driver that
fills NodeEntered.activity / NodeProduced.headline directly, in any language
(see spec section 6)."""
from __future__ import annotations

from poor_code.domain.session.models import CodeContext, Phase, Plan

_ACTIVITY = {
    "router": "Routing the request",
    "explorer": "Exploring the codebase",
    "locator": "Locating relevant code",
    "understanding_gate": "Checking the findings are sufficient",
    "interviewer": "Asking a clarifying question",
    "spec_confirm_gate": "Confirming the spec with you",
    "planner": "Drafting the implementation plan",
    "plan_reviewer": "Reviewing the plan",
    "acceptance_oracle": "Designing acceptance criteria",
    "acceptance_critic": "Critiquing the acceptance criteria",
    "acceptance_gate": "Checking the acceptance criteria",
    "plan_gate": "Checking the plan",
    "plan_confirm_gate": "Confirming the plan with you",
    "provisioner": "Preparing the environment",
    "composer": "Composing the tasks",
    "task_selector": "Selecting the next task",
    "eng_gate": "Checking it can proceed",
    "implementer": "Writing the code",
    "validator": "Validating the change",
    "validation_runner": "Running validation",
    "completion_gate": "Checking task completion",
    "failure_analyst": "Analyzing the failure",
    "global_validator": "Final full validation",
    "reporter": "Summarizing the result",
    "fast_path": "Handling this quickly",
}

_PHASE_FALLBACK = {
    Phase.ROUTING: "Routing the request",
    Phase.LOCATING: "Exploring the code",
    Phase.INTERVIEWING: "Confirming requirements",
    Phase.PLANNING: "Refining the plan",
    Phase.IMPLEMENTING: "Working on the tasks",
    Phase.FINALIZING: "Wrapping up",
}


class StaticNarrator:
    def activity(self, node: str, phase, state) -> str:
        hint = getattr(state, "repair_hint", None)
        if node == "planner" and hint:
            return f"Revising the plan to address: '{hint}'"
        if node in _ACTIVITY:
            return _ACTIVITY[node]
        return _PHASE_FALLBACK.get(phase, "Working")

    def summary(self, node: str, result) -> tuple[str, tuple[str, ...]]:
        out = getattr(result, "output", None)
        if node in ("explorer", "locator") and isinstance(out, CodeContext):
            n_files = len({r.file for r in out.candidates})
            n_tests = len(out.related_tests)
            ground = out.grounding.value if out.grounding else "?"
            files_w = "file" if n_files == 1 else "files"
            tests_w = "test" if n_tests == 1 else "tests"
            headline = f"Found {n_files} {files_w} · {n_tests} {tests_w} (grounding: {ground})"
            detail = tuple(r.file for r in out.candidates[:8])
            return headline, detail
        if node == "planner" and isinstance(out, Plan):
            tasks_w = "task" if len(out.tasks) == 1 else "tasks"
            headline = f"{len(out.tasks)} {tasks_w} planned"
            detail = tuple(f"{i}. {t.title}" for i, t in enumerate(out.tasks, 1))
            return headline, detail
        return "", ()
