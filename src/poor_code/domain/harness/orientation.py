# src/poor_code/domain/harness/orientation.py
"""Deterministic 'HARNESS POSITION' block — a pure function of (node, state),
rendered by the harness (never the model). Prepended to each agent node's prompt
to orient the weak model and tell it what happens to its output next (which
discourages stubbing). See design.md spec section G."""
from __future__ import annotations

from poor_code.domain.session.models import SessionState, TaskStatus

# (label, node_name) in pipeline order. Gates are deterministic → omitted.
_STAGES: tuple[tuple[str, str], ...] = (
    ("explore", "explorer"),
    ("interview", "interviewer"),
    ("plan", "planner"),
    ("implement", "implementer"),
    ("validate", "validation_runner"),
    ("report", "reporter"),
)
# validate/report intentionally have no _ROLE/_AFTER entry — raw name is fine.

_ROLE: dict[str, str] = {
    "explorer": "LOCATING — you are the Explorer.",
    "interviewer": "INTERVIEWING — you are the Interviewer.",
    "planner": "PLANNING — you are the Planner.",
    "implementer": "IMPLEMENTING — you are the Implementer.",
}

_AFTER: dict[str, str] = {
    "explorer": "After you: the Interviewer turns your findings into a binding spec.",
    "interviewer": "After you: the Planner breaks your spec into tasks.",
    "planner": "After you: PlanGate checks your plan, then the Implementer builds each task.",
    "implementer": "After this task: ValidationRunner runs your VALIDATION; pass -> next task, fail -> you retry.",
}


def render_position(node_name: str, state: SessionState) -> str:
    lines = [
        "HARNESS POSITION",
        f"  Stage: {_ROLE.get(node_name, node_name)}",
        f"  Pipeline: {_pipeline(node_name, state)}",
        f"  Progress: {_progress(state)}",
    ]
    after = _AFTER.get(node_name)
    if after:
        lines.append(f"  {after}")
    return "\n".join(lines)


def _stage_done(node_name: str, state: SessionState) -> bool:
    if node_name == "explorer":
        return state.understanding is not None
    if node_name == "interviewer":
        return state.requirement is not None
    if node_name == "planner":
        return state.plan is not None
    if node_name == "implementer":
        return _all_tasks_done(state)
    return False  # validate / report: never pre-marked done


def _pipeline(current: str, state: SessionState) -> str:
    parts: list[str] = []
    for label, node in _STAGES:
        if node == current:
            parts.append(f"[{label.upper()} ▶]")
        elif _stage_done(node, state):
            parts.append(f"{label} ✓")
        else:
            parts.append(label)
    return " → ".join(parts)


def _all_tasks_done(state: SessionState) -> bool:
    if state.plan is None or not state.plan.tasks:
        return False
    return all(t.status is TaskStatus.DONE for t in state.plan.tasks)


def _progress(state: SessionState) -> str:
    bits: list[str] = []
    bits.append("request captured" if state.request is not None else "request pending")
    cc = state.understanding
    if cc is not None:
        if cc.candidates:
            bits.append(f"located ({len(cc.candidates)} candidates)")
        else:
            bits.append(f"located ({cc.grounding.value})")
    if state.requirement is not None:
        bits.append(f"requirement set ({len(state.requirement.acceptance)} acceptance)")
    if state.plan is not None and state.plan.tasks:
        bits.append(_plan_progress(state))
    return "; ".join(bits) + "."


def _plan_progress(state: SessionState) -> str:
    tasks = state.plan.tasks
    cur = state.cursor.task_id if state.cursor is not None else None
    done = [t.id for t in tasks if t.status is TaskStatus.DONE]
    doing = next((t for t in tasks if t.id == cur and t.status is not TaskStatus.DONE), None)
    left = [t.id for t in tasks if t.status is not TaskStatus.DONE and t.id != cur]
    s = f"plan has {len(tasks)} task{'s' if len(tasks) != 1 else ''}"
    if done:
        s += f"; done: {', '.join(done)}"
    if doing is not None:
        s += f'; doing: {doing.id} "{doing.title}"'
    if left:
        s += f"; left: {', '.join(left)}"
    return s
