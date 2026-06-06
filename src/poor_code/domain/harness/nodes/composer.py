"""composer [C] — deterministic Task-context assembler. Projects the understanding
layer's CodeRefs down to those touching this Task's edit scope, so the implementer's
prompt is focused. snippet is left None in slice-1 (filled in a later slice)."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.session.models import CodeContext, Phase, TaskContext


class Composer:
    name = "composer"
    phase = Phase.IMPLEMENTING

    async def run(self, ctx: NodeContext) -> NodeResult:
        state = ctx.state
        assert state.plan is not None and state.cursor is not None
        task = next((t for t in state.plan.tasks if t.id == state.cursor.task_id), None)
        assert task is not None, f"cursor task_id {state.cursor.task_id!r} not in plan"
        cc = state.understanding or CodeContext()
        scope = set(task.edit_scope.editable) | set(task.edit_scope.readonly)
        refs = tuple(r for r in cc.candidates if r.file in scope)
        return NodeResult(output=TaskContext(refs=refs, snippet=None))
