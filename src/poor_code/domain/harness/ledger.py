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


def task_section(plan, task_id: str) -> str:
    """Return the '## <task_id>' markdown block from plan.plan_md (sliced to the next
    '## ' heading), falling back to the whole md or the id. Matches the heading by a
    full token so '## t1' does NOT match '## t10'."""
    md = (plan.plan_md if plan else "") or ""
    for i, line in _iter_section_starts(md):
        head = line[3:].strip()           # text after "## "
        # token before ':' or whitespace must equal task_id exactly
        token = head.split(":", 1)[0].split()[0] if head else ""
        if token == task_id:
            j = md.find("\n## ", i + 1)
            return md[i:] if j == -1 else md[i:j]
    return md or task_id


def has_section(md: str, task_id: str) -> bool:
    """True if plan_md has a '## <task_id>' heading matching the id as a full token
    (so 't1' does not match 't10'). Mirrors task_section's matching."""
    md = md or ""
    for _, line in _iter_section_starts(md):
        head = line[3:].strip()
        token = head.split(":", 1)[0].split()[0] if head else ""
        if token == task_id:
            return True
    return False


def _iter_section_starts(md: str):
    idx = 0
    for line in md.splitlines(keepends=True):
        if line.startswith("## "):
            yield idx, line
        idx += len(line)


def render_acceptance(state) -> str:
    """Format the full acceptance spec as '  - (criterion) command' lines, or '  (none)'."""
    checks = state.acceptance.checks if state.acceptance else ()
    return "\n".join(f"  - ({c.criterion}) {c.command}" for c in checks) or "  (none)"


def _green_checks(task) -> list[str]:
    for attempt in reversed(task.attempts):
        if attempt.check_results:
            return [crit for crit, ok in attempt.check_results if ok]
    return []
