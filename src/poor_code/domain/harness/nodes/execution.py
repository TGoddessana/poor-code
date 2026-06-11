# src/poor_code/domain/harness/nodes/execution.py
"""Execution-layer deterministic [C] nodes: task_selector, eng_gate,
validation_runner, completion_gate. Smarts that need an LLM (composer,
implementer, validator, ...) live in their own AgentNode modules."""
from __future__ import annotations

import asyncio
from pathlib import Path

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.session.models import (
    AttemptStatus,
    Layer,
    Phase,
    SelectedTask,
    TaskCompleted,
    TaskStatus,
    ValidationResult,
    Verdict,
    VerdictKind,
)

MAX_ATTEMPTS = 3  # implementer retries per Task before escalate (spec §5 cap)


def _active(state):
    """Return (task, latest_attempt) for the cursor's active task. attempt may be None."""
    assert state.plan is not None and state.cursor is not None
    task = next((t for t in state.plan.tasks if t.id == state.cursor.task_id), None)
    assert task is not None, f"cursor task_id {state.cursor.task_id!r} not in plan"
    attempt = task.attempts[-1] if task.attempts else None
    return task, attempt


class TaskSelector:
    """Middle-cycle walker: choose the next runnable Task or signal done."""

    name = "task_selector"
    phase = Phase.IMPLEMENTING

    async def run(self, ctx: NodeContext) -> NodeResult:
        plan = ctx.state.plan
        assert plan is not None, "task_selector requires a plan"
        done = {t.id for t in plan.tasks if t.status is TaskStatus.DONE}
        deps: dict[str, list[str]] = {}
        for d in plan.deps:
            deps.setdefault(d.task_id, []).append(d.depends_on)
        for t in plan.tasks:
            if t.status not in (TaskStatus.PENDING, TaskStatus.ACTIVE):
                continue
            if all(dep in done for dep in deps.get(t.id, ())):
                return NodeResult(output=SelectedTask(task_id=t.id), branch="task")
        return NodeResult(branch="done")


class EngGate:
    """Structural guard on the latest Attempt: it must have a patch and must never
    touch a forbidden path. Whether the edits FIT the task (scope appropriateness) is
    the validator's semantic call, not a mechanical allowlist — a task that fixes
    src/x.py may also edit its test tests/test_x.py without declaring it, and the
    reviewer judges that instead of the gate killing it. eng_gate keeps only the two
    hard, judgment-free floors: there is something to review, and nothing forbidden."""

    name = "eng_gate"
    phase = Phase.IMPLEMENTING

    async def run(self, ctx: NodeContext) -> NodeResult:
        # function-local import: validator imports run_shell from this module, so a
        # module-level import of MAX_ADVERSARIAL_ROUNDS here would be a circular import.
        from poor_code.domain.harness.nodes.validator import MAX_ADVERSARIAL_ROUNDS
        task, attempt = _active(ctx.state)
        hint = self._invalid_hint(task, attempt)
        if hint is None:
            return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
        if attempt is not None and attempt.adversarial_rounds >= MAX_ADVERSARIAL_ROUNDS:
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query=(f"eng_gate: implementation still structurally invalid after "
                       f"{MAX_ADVERSARIAL_ROUNDS} refinements: {hint}")))
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION, hint=hint))

    @staticmethod
    def _invalid_hint(task, attempt) -> str | None:
        if attempt is None or attempt.patch is None or not attempt.patch.files:
            return "Attempt has no patch."
        forbidden = set(task.edit_scope.forbidden)
        for f in attempt.patch.files:
            if f in forbidden:
                return f"Edited forbidden path: {f}"
        return None


_OUTPUT_LIMIT = 30_000
_DEFAULT_TIMEOUT = 120


async def run_shell(
    command: str, cwd: Path, cancel: asyncio.Event, timeout: int = _DEFAULT_TIMEOUT
) -> tuple[int, str]:
    """Run a shell command in cwd; return (exit_code, truncated combined output).
    Honors cancel (kills the process) and a timeout (exit 124)."""
    if cancel.is_set():
        raise asyncio.CancelledError
    proc = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, cwd=str(cwd))

    async def _cancel_on_event() -> None:
        await cancel.wait()
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    cancel_task = asyncio.create_task(_cancel_on_event())
    try:
        try:
            out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, f"[command timed out after {timeout}s]"
    finally:
        cancel_task.cancel()

    if cancel.is_set():
        raise asyncio.CancelledError
    return proc.returncode, out_bytes.decode("utf-8", errors="replace")[:_OUTPUT_LIMIT]


def _prev_green_criteria(state, task) -> set[str]:
    """Criteria that were GREEN on an EARLIER attempt of THIS task (union over the
    task's prior attempts' check_results). Excludes the cursor's latest attempt so a
    just-recorded result never counts itself as a baseline. This is the no-regression
    floor: a check that was once green must stay green."""
    latest_id = state.cursor.attempt_id if state.cursor is not None else None
    green: set[str] = set()
    for a in task.attempts:
        if a.id == latest_id:
            continue
        green |= {crit for crit, ok in a.check_results if ok}
    return green


def _green_from_other_tasks(state, task) -> set[str]:
    """Acceptance criteria already GREEN from OTHER tasks' attempts — the build's
    progress baseline coming into THIS task. A task may only complete when it either
    reaches FULL green or STRICTLY adds to this baseline; treading water (leaving the
    green set unchanged) is not 'done'. Without this, the no-regression floor passes a
    task at 0/N green whenever there is nothing yet to regress (the false-completion
    bug: completion_gate stamped 'done' on 0/4 and 1/4 acceptance results)."""
    if state.plan is None:
        return set()
    green: set[str] = set()
    for t in state.plan.tasks:
        if t.id == task.id:
            continue
        for a in t.attempts:
            green |= {crit for crit, ok in a.check_results if ok}
    return green


class ValidationRunner:
    """Binding pass/fail ★. Runs the GLOBAL acceptance spec (Task.how_to_validate is
    usually empty now): PASS when no PREVIOUSLY-GREEN acceptance check has regressed,
    FAIL (with a regression hint) otherwise. Persists this attempt's per-check results
    too. Falls back to Task.how_to_validate when there is NO acceptance spec."""

    name = "validation_runner"
    phase = Phase.IMPLEMENTING

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    async def run(self, ctx: NodeContext) -> NodeResult:
        task, _ = _active(ctx.state)
        checks = ctx.state.acceptance.checks if ctx.state.acceptance else ()
        if not checks:
            # fallback: old behavior so non-acceptance flows still work
            command = task.how_to_validate
            exit_code, output = await run_shell(command, self._cwd, ctx.cancel)
            passed = exit_code == 0
            result = ValidationResult(
                command=command, exit_code=exit_code, passed=passed, output=output)
            return NodeResult(output=result, branch="pass" if passed else "fail")

        prev_green = _prev_green_criteria(ctx.state, task)
        other_green = _green_from_other_tasks(ctx.state, task)
        results: list[tuple[str, bool]] = []
        outputs: list[str] = []
        for c in checks:
            code, out = await run_shell(c.command, self._cwd, ctx.cancel)
            results.append((c.criterion, code == 0))
            if code != 0:
                outputs.append(f"[{c.criterion}] exit {code}: {clamp_tool_output(out)}")
        all_criteria = {c.criterion for c in checks}
        now_green = {crit for crit, ok in results if ok}
        # No-regression floor: nothing once green (here or in a sibling task) may go red.
        regressed = sorted((prev_green | other_green) - now_green)
        # Forward-progress floor: 'done' requires FULL green OR at least one acceptance
        # check this task newly turned green. A task that adds nothing is not complete —
        # this is what stops completion_gate from stamping 'done' on a 0/N result.
        made_progress = now_green == all_criteria or bool(now_green - other_green)
        passed = (not regressed) and made_progress
        if regressed:
            summary = "regressed: " + ", ".join(regressed)
        elif not made_progress:
            summary = (f"no acceptance progress: {len(now_green)}/{len(checks)} green, "
                       "none newly satisfied by this task")
        else:
            summary = ("all known-green checks still pass; "
                       f"{len(now_green)}/{len(checks)} acceptance checks green")
        result = ValidationResult(
            command="; ".join(c.command for c in checks),
            exit_code=0 if passed else 1,
            passed=passed,
            output=summary + ("\n" + "\n".join(outputs) if outputs else ""),
            check_results=tuple(results))
        return NodeResult(output=result, branch="pass" if passed else "fail")


class CompletionGate:
    """Single code chokepoint after validation. Pass → task done. Fail below the
    attempt cap → repair(impl). Fail at cap → escalate (Plan 4 turns this into a
    full-auto partial under a Policy)."""

    name = "completion_gate"
    phase = Phase.IMPLEMENTING

    async def run(self, ctx: NodeContext) -> NodeResult:
        task, attempt = _active(ctx.state)
        rr = attempt.run_result if attempt is not None else None
        if rr is not None and rr.passed:
            return NodeResult(
                output=TaskCompleted(task_id=task.id, attempt_id=attempt.id),
                branch="done")
        if len(task.attempts) >= MAX_ATTEMPTS:
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query=(f"Task {task.id} still failing after {MAX_ATTEMPTS} attempts: "
                       f"{'' if rr is None else clamp_tool_output(rr.output, head=200, tail=600)}")))
        hint = "Validation failed; fix the implementation."
        if rr is not None and rr.output:
            hint = (f"Validation failed (exit {rr.exit_code}). Fix it. Output:\n"
                    f"{clamp_tool_output(rr.output, head=400, tail=1100)}")
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION, hint=hint))
