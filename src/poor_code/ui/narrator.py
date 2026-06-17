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

from poor_code.domain.session.models import (
    Attempt,
    ChecksObserved,
    EnvReport,
    FeedbackEntry,
    Phase,
    Plan,
    SelectedTask,
    TaskCompleted,
    TaskContext,
    ValidationResult,
    VerdictKind,
    CodeContext,
)

_ACTIVITY = {
    "router": "Routing the request",
    "explorer": "Exploring the codebase",
    "locator": "Locating relevant code",
    "understanding_gate": "Checking the findings are sufficient",
    "interviewer": "Asking a clarifying question",
    "spec_confirm_gate": "Confirming the spec with you",
    "planner": "Drafting the implementation plan",
    "plan_reviewer": "Reviewing the plan",
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
        task = _active_task_label(state)
        if task:
            match node:
                case "task_selector":
                    return "Selecting the next task"
                case "composer":
                    return f"Gathering context for {task}"
                case "implementer":
                    return f"Writing code for {task}"
                case "eng_gate":
                    return f"Checking patch structure for {task}"
                case "validator":
                    return f"Reviewing the patch for {task}"
                case "validation_runner":
                    return f"Running validation for {task}"
                case "completion_gate":
                    return f"Checking completion for {task}"
                case "failure_analyst":
                    return f"Analyzing failure for {task}"
        if node in _ACTIVITY:
            return _ACTIVITY[node]
        return _PHASE_FALLBACK.get(phase, "Working")

    def summary(self, node: str, result) -> tuple[str, tuple[str, ...]]:
        out = getattr(result, "output", None)
        verdict = getattr(result, "verdict", None)
        if node in ("explorer", "locator") and isinstance(out, CodeContext):
            n_files = len({r.file for r in out.candidates})
            n_tests = len(out.related_tests)
            files_w = "file" if n_files == 1 else "files"
            tests_w = "test" if n_tests == 1 else "tests"
            headline = f"Found {n_files} {files_w} · {n_tests} {tests_w}"
            # grounding is only meaningful when NOTHING was found — showing
            # "(grounding: not_found)" alongside real candidates reads as a failure when
            # the gate in fact advanced on those candidates (see gates.UnderstandingGate).
            if not out.candidates:
                ground = out.grounding.value if out.grounding else "?"
                headline += f" (grounding: {ground})"
            # Label each ref as file::symbol (not bare file) and de-dup, so many symbols of
            # one file don't render as the same line repeated.
            seen: set[str] = set()
            detail: list[str] = []
            for r in out.candidates:
                label = r.file if r.symbol is None else f"{r.file}::{r.symbol}"
                if label in seen:
                    continue
                seen.add(label)
                detail.append(label)
                if len(detail) >= 8:
                    break
            return headline, tuple(detail)
        if node == "planner" and isinstance(out, Plan):
            tasks_w = "task" if len(out.tasks) == 1 else "tasks"
            headline = f"{len(out.tasks)} {tasks_w} planned"
            detail = tuple(f"{i}. {t.title}" for i, t in enumerate(out.tasks, 1))
            return headline, detail
        if node == "validation_runner" and isinstance(out, ValidationResult):
            status = "passed" if out.passed else "failed"
            detail = [out.command]
            if out.output:
                detail.append(out.output[:500])
            return f"Validation {status} (exit {out.exit_code})", tuple(detail)
        if node == "validator" and isinstance(out, ChecksObserved):
            passed = sum(1 for _, ok in out.results if ok)
            total = len(out.results)
            detail = [f"{crit}: {'PASS' if ok else 'FAIL'}" for crit, ok in out.results[:5]]
            if verdict is not None and verdict.hint:
                detail.append(f"Hint: {verdict.hint}")
            return f"Validator observed {passed}/{total} checks passing", tuple(detail)
        if node == "failure_analyst" and isinstance(out, FeedbackEntry):
            return (
                f"Failure lesson: {out.failure_type or 'unknown'}",
                tuple(x for x in (out.symptom, out.prevention_hint) if x),
            )
        if node == "implementer" and isinstance(out, Attempt):
            files = out.patch.files if out.patch else ()
            files_w = "file" if len(files) == 1 else "files"
            return f"Attempt {out.id} changed {len(files)} {files_w}", tuple(files[:8])
        if node == "provisioner" and isinstance(out, EnvReport):
            status = "ready" if out.ready else "not ready"
            detail = tuple(x for x in (out.test_command, out.notes) if x)
            return f"Environment {status}", detail
        if node == "composer" and isinstance(out, TaskContext):
            refs_w = "ref" if len(out.refs) == 1 else "refs"
            return f"{len(out.refs)} task context {refs_w}", tuple(r.file for r in out.refs[:8])
        if node == "task_selector" and isinstance(out, SelectedTask):
            return f"Selected task {out.task_id}", ()
        if node == "completion_gate" and isinstance(out, TaskCompleted):
            return f"Completed task {out.task_id}", (f"attempt {out.attempt_id}",)
        if verdict is not None:
            return _verdict_summary(node, verdict)
        return "", ()


def _verdict_summary(node: str, verdict) -> tuple[str, tuple[str, ...]]:
    kind = getattr(verdict, "kind", None)
    layer = getattr(verdict, "layer", None)
    hint = getattr(verdict, "hint", None) or getattr(verdict, "query", None)
    layer_text = f" ({layer.value})" if layer is not None else ""
    if kind is VerdictKind.ADVANCE:
        return f"{node} approved{layer_text}", tuple([hint] if hint else [])
    if kind is VerdictKind.REPAIR:
        return f"{node} requested repair{layer_text}", tuple([hint] if hint else [])
    if kind is VerdictKind.ESCALATE:
        return f"{node} escalated{layer_text}", tuple([hint] if hint else [])
    return "", ()


def _active_task_label(state) -> str:
    cursor = getattr(state, "cursor", None)
    plan = getattr(state, "plan", None)
    task_id = getattr(cursor, "task_id", None) if cursor is not None else None
    if not task_id:
        return ""
    title = ""
    for task in getattr(plan, "tasks", ()) if plan is not None else ():
        if task.id == task_id:
            title = task.title
            break
    return f"{task_id}: {title}" if title else task_id
