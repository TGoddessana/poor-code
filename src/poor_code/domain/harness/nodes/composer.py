"""composer [C] — deterministic Task-context assembler. The implementer is the only
node that writes code, so it must receive the code, not just file names. The composer
projects the understanding layer into a single `snippet`: the verbatim file bodies the
explorer read (role-labeled EDITABLE/READONLY/REFERENCE, clipped per file), the other
candidate files as read-on-demand pointers, and the explorer's confusers as explicit
anti-targets. `refs` carries every candidate (not a scope-filtered subset) for the
record; the implementer renders `snippet`."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.session.models import CodeContext, Phase, Plan, Task, TaskContext

# Per-file body slice handed to the implementer as ground truth. Mirrors
# acceptance_oracle._MAX_EXCERPT_IN_PROMPT so the two nodes clip identically.
_MAX_EXCERPT_IN_PROMPT = 1800


class Composer:
    name = "composer"
    phase = Phase.IMPLEMENTING
    requires = (Plan, CodeContext)
    produces = ()

    async def run(self, ctx: NodeContext) -> NodeResult:
        state = ctx.state
        state.require(Plan)
        assert state.cursor is not None
        task = next((t for t in state.plan.tasks if t.id == state.cursor.task_id), None)
        assert task is not None, f"cursor task_id {state.cursor.task_id!r} not in plan"
        cc = state.understanding or CodeContext()
        return NodeResult(output=TaskContext(
            refs=cc.candidates, snippet=self._build_snippet(task, cc)))

    @staticmethod
    def _role(path: str, task: Task) -> str:
        if path in task.edit_scope.editable:
            return "EDITABLE"
        if path in task.edit_scope.readonly:
            return "READONLY"
        return "REFERENCE"

    @staticmethod
    def _where(ref) -> str:
        return ref.file if ref.symbol is None else f"{ref.file}::{ref.symbol}"

    @classmethod
    def _build_snippet(cls, task: Task, cc: CodeContext) -> str | None:
        lines: list[str] = []
        # 1) verbatim bodies the explorer actually read, role-labeled and clipped
        for ex in cc.excerpts:
            body = ex.text[:_MAX_EXCERPT_IN_PROMPT]
            trunc = (" …(truncated)"
                     if (ex.truncated or len(ex.text) > _MAX_EXCERPT_IN_PROMPT) else "")
            lines.append(f"--- {ex.path} [{cls._role(ex.path, task)}]{trunc} ---\n{body}")
        # 2) candidate files with no body — pointers to read on demand
        bodied = {ex.path for ex in cc.excerpts}
        others = [r for r in cc.candidates if r.file not in bodied]
        if others:
            lines.append("Other relevant files (read with bash if you need their contents):")
            lines.extend(f"  - {cls._where(r)} [{cls._role(r.file, task)}]" for r in others)
        # 3) confusers — resemble the target but are the WRONG file
        if cc.confusers:
            lines.append("NOT these (resemble the target but are the WRONG file — do not edit):")
            lines.extend(f"  - {cls._where(r)}" for r in cc.confusers)
        return "\n".join(lines) if lines else None
