# src/poor_code/domain/harness/nodes/execution.py
"""Execution-layer deterministic [C] nodes: task_selector, eng_gate,
validation_runner, completion_gate. Smarts that need an LLM (composer,
implementer, validator, ...) live in their own AgentNode modules."""
from __future__ import annotations

import asyncio
from pathlib import Path

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.nodes.validator import MAX_ADVERSARIAL_ROUNDS
from poor_code.domain.session.models import (
    AttemptStatus,
    Layer,
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
    """Structural guard on the latest Attempt: must have a patch, and every
    changed file must be inside edit_scope.editable and never in forbidden."""

    name = "eng_gate"

    async def run(self, ctx: NodeContext) -> NodeResult:
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
        editable = set(task.edit_scope.editable)
        forbidden = set(task.edit_scope.forbidden)
        for f in attempt.patch.files:
            if f in forbidden:
                return f"Edited forbidden path: {f}"
            if editable and f not in editable:
                return f"Edited path outside editable scope: {f}"
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


class ValidationRunner:
    """Binding pass/fail ★. Re-runs Task.how_to_validate as code; exit code decides."""

    name = "validation_runner"

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    async def run(self, ctx: NodeContext) -> NodeResult:
        task, _ = _active(ctx.state)
        command = task.how_to_validate
        exit_code, output = await run_shell(command, self._cwd, ctx.cancel)
        passed = exit_code == 0
        result = ValidationResult(
            command=command, exit_code=exit_code, passed=passed, output=output)
        return NodeResult(output=result, branch="pass" if passed else "fail")


class CompletionGate:
    """Single code chokepoint after validation. Pass → task done. Fail below the
    attempt cap → repair(impl). Fail at cap → escalate (Plan 4 turns this into a
    full-auto partial under a Policy)."""

    name = "completion_gate"

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
                       f"{'' if rr is None else rr.output[:200]}")))
        hint = "Validation failed; fix the implementation."
        if rr is not None and rr.output:
            hint = f"Validation failed (exit {rr.exit_code}). Fix it. Output:\n{rr.output[:500]}"
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION, hint=hint))
