"""Deterministic struct -> markdown for the human confirmation gates (display only)."""
from __future__ import annotations

from poor_code.domain.session.models import AcceptanceSpec, Plan, Requirement


def render_spec_md(req: Requirement, accept: AcceptanceSpec | None) -> str:
    lines = [f"# Spec\n\n**Goal:** {req.summary}\n"]
    if req.acceptance:
        lines.append("## Acceptance criteria\n" + "\n".join(f"- {a}" for a in req.acceptance))
    if req.out_of_scope:
        lines.append("## Out of scope\n" + "\n".join(f"- {a}" for a in req.out_of_scope))
    if req.assumptions:
        lines.append("## Assumptions\n" + "\n".join(f"- {a}" for a in req.assumptions))
    if accept and accept.checks:
        lines.append("## Acceptance checks (runnable)\n" +
                     "\n".join(f"- `{c.command}`  — {c.criterion}" for c in accept.checks))
    return "\n\n".join(lines)


def render_plan_md(plan: Plan) -> str:
    body = plan.plan_md or ""
    if plan.deps:
        edges = ", ".join(f"{d.task_id}<-{d.depends_on}" for d in plan.deps)
        body += f"\n\n_deps: {edges}_"
    return body
