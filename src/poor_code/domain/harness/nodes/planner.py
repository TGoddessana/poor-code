# src/poor_code/domain/harness/nodes/planner.py
"""Planner — converts a binding Requirement into bounded implementation tasks.

This is still a thin AgentNode: it does not inspect file bodies or execute tools.
It receives Requirement as binding input and CodeContext as reference material,
then emits a Plan through one structured-output tool call.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from poor_code.domain.harness.node import AgentNode, _LLMClientLike
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import (
    CodeRef,
    Dependency,
    EditScope,
    GroundingStatus,
    Plan,
    SessionState,
    Task,
)

_TOOL_NAME = "emit_plan"

_SYSTEM = (
    "You are the Planner in a software-engineering harness. Convert the binding "
    "Requirement into small bounded engineering Tasks. Every task MUST have a "
    "non-empty edit_scope.editable and non-empty how_to_validate. Use task ids "
    "t1, t2, ... for dependencies. New files belong in edit_scope.editable. "
    "CodeContext is reference material, not binding truth. Call emit_plan once."
)


class _EditScopeOut(BaseModel):
    editable: list[str] = []
    readonly: list[str] = []
    forbidden: list[str] = []


class _TaskOut(BaseModel):
    title: str
    purpose: str
    description: str = ""
    edit_scope: _EditScopeOut = Field(default_factory=_EditScopeOut)
    how_to_validate: str = ""


class _DependencyOut(BaseModel):
    task_id: str
    depends_on: str


class _PlanOut(BaseModel):
    tasks: list[_TaskOut] = []
    deps: list[_DependencyOut] = []


class Planner(AgentNode):
    name = "planner"

    def __init__(self, llm: _LLMClientLike, project_map: ProjectMap) -> None:
        super().__init__(llm)
        self._map = project_map

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        assert state.requirement is not None, "Planner requires state.requirement"
        req = state.requirement
        return [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    "REQUIREMENT:\n"
                    f"summary: {req.summary}\n"
                    f"acceptance:\n{self._bullets(req.acceptance)}\n"
                    f"out_of_scope:\n{self._bullets(req.out_of_scope)}\n"
                    f"assumptions:\n{self._bullets(req.assumptions)}\n"
                    f"open_questions:\n{self._bullets(req.open_questions)}\n\n"
                    f"CODE CONTEXT:\n{self._context_digest(state)}"
                ),
            },
        ]

    def output_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": "Emit bounded implementation tasks and dependencies.",
                "parameters": inline_refs(_PlanOut.model_json_schema()),
            },
        }

    def output_model(self) -> type[BaseModel]:
        return _PlanOut

    def parse(self, args_json: str) -> Plan:
        out = _PlanOut.model_validate_json(args_json)
        tasks = tuple(self._to_task(i, task) for i, task in enumerate(out.tasks, start=1))
        deps = tuple(
            Dependency(task_id=dep.task_id, depends_on=dep.depends_on)
            for dep in out.deps
        )
        return Plan(tasks=tasks, deps=deps)

    @staticmethod
    def _to_task(index: int, task: _TaskOut) -> Task:
        return Task(
            id=f"t{index}",
            title=task.title,
            purpose=task.purpose,
            description=task.description,
            edit_scope=EditScope(
                editable=tuple(task.edit_scope.editable),
                readonly=tuple(task.edit_scope.readonly),
                forbidden=tuple(task.edit_scope.forbidden),
            ),
            how_to_validate=task.how_to_validate,
        )

    @staticmethod
    def _bullets(items: tuple[str, ...]) -> str:
        if not items:
            return "  (none)"
        return "\n".join(f"  - {item}" for item in items)

    def _context_digest(self, state: SessionState) -> str:
        cc = state.understanding
        if cc is None:
            return "(none)"
        lines: list[str] = []
        if cc.grounding is GroundingStatus.GREENFIELD:
            lines.append(
                "MODE: greenfield (create-from-scratch — no existing code to ground; "
                "absence of candidates is expected, not a failure)."
            )
        if cc.summary:
            lines.append(f"summary: {cc.summary}")
        for label, refs in (
            ("candidates", cc.candidates),
            ("confusers", cc.confusers),
            ("related_tests", cc.related_tests),
        ):
            lines.append(f"{label}:")
            if not refs:
                lines.append("  (none)")
            for ref in refs:
                lines.append(f"  - {self._render_ref(ref)}")
        for ex in cc.excerpts:
            body = ex.text if len(ex.text) <= 600 else ex.text[:600] + " …"
            lines.append(f"--- {ex.path}{' (truncated)' if ex.truncated else ''} ---\n{body}")
        return "\n".join(lines)

    def _render_ref(self, ref: CodeRef) -> str:
        where = ref.file if ref.symbol is None else f"{ref.file}::{ref.symbol}"
        sig = self._signature_of(ref)
        return f"{where}  {sig}" if sig else where

    def _signature_of(self, ref: CodeRef) -> str | None:
        if ref.symbol is None:
            return None
        for file_entry in self._map.files:
            if file_entry.path == ref.file:
                for symbol in file_entry.symbols:
                    if symbol.name == ref.symbol:
                        return symbol.signature
        return None
