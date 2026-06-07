"""render_build_ledger — a bounded narrative of completed work, shared by the
implementer and the validator so both reason from one source of truth. NOT a code
dump: cumulative code lives on the workspace filesystem (tasks run sequentially);
the ledger carries WHAT was done and WHICH acceptance checks went green."""
from __future__ import annotations

from poor_code.domain.session.models import SessionState, TaskStatus


def render_build_ledger(state: SessionState) -> str:
    plan = state.plan
    if plan is None:
        return "(no completed work yet)"
    lines: list[str] = []
    for task in plan.tasks:
        if task.status is not TaskStatus.DONE:
            continue
        green = _green_checks(task)
        suffix = f" — acceptance green: {', '.join(green)}" if green else ""
        lines.append(f"{task.id} ✓ {task.title}{suffix}")
    return "\n".join(lines) if lines else "(no completed work yet)"


def _green_checks(task) -> list[str]:
    for attempt in reversed(task.attempts):
        if attempt.check_results:
            return [crit for crit, ok in attempt.check_results if ok]
    return []
