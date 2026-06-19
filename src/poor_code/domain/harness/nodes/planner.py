# src/poor_code/domain/harness/nodes/planner.py
"""Planner — converts a binding Requirement into bounded implementation tasks.

A thin AgentNode: it does not inspect file bodies or execute tools.
It receives Requirement as binding input and CodeContext as reference material,
then emits a Plan through one structured-output tool call.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import AgentNode, _LLMClientLike, validate_output
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import (
    CodeContext,
    CodeRef,
    Dependency,
    EditScope,
    FileSlot,
    GroundingStatus,
    Phase,
    Plan,
    Requirement,
    SessionState,
    Step,
    StepKind,
    Task,
    effective_requirement,
)

_TOOL_NAME = "emit_plan"


_SYSTEM = (
    "You are the Planner. Produce an implementation plan as MARKDOWN plus a tiny machine "
    "skeleton, in ONE emit_plan call.\n"
    "- plan_md: a markdown plan. One '## <task-id>: <files> — <what & why>' section per task. "
    "Describe WHAT to implement and WHICH acceptance criteria it targets. Prose is fine; do NOT "
    "emit JSON inside plan_md.\n"
    "- tasks: for each section, {id, title, purpose, editable:[files it edits, 1-3], "
    "depends_on:[task ids]}. purpose is ONE line: what this task delivers and which "
    "acceptance criterion it targets.\n"
    "RULES: one task = one patch-sized deliverable (default FEWER tasks; merge when unsure). Every "
    "task's editable must be a real file the task touches. Do not invent files outside the chosen "
    "stack. The implementer is an agent and will derive concrete steps itself — you do NOT write "
    "code steps or validation commands here.\n"
)


class _StepOut(BaseModel):
    kind: str = "impl"          # "test" | "impl" | "run"
    file: str = ""
    anchor: str = ""
    body: str = ""
    run: str = ""
    expected: str = ""


class _FileSlotOut(BaseModel):
    path: str
    responsibility: str = ""


class _SkeletonTaskOut(BaseModel):
    id: str
    title: str = ""
    purpose: str = ""
    editable: list[str] = []
    depends_on: list[str] = []
    how_to_validate: str = ""
    steps: list[_StepOut] = []


class _PlanOut(BaseModel):
    plan_md: str = ""
    file_plan: list[_FileSlotOut] = []
    tasks: list[_SkeletonTaskOut] = []


_STEP_KINDS = {"test": StepKind.TEST, "impl": StepKind.IMPL, "run": StepKind.RUN}


def _coerce_steps(raw_steps: list[_StepOut], task_id: str) -> tuple[Step, ...]:
    out: list[Step] = []
    for i, s in enumerate(raw_steps, start=1):
        kind = _STEP_KINDS.get((s.kind or "impl").strip().lower(), StepKind.IMPL)
        out.append(Step(id=f"{task_id}-s{i}", kind=kind, file=s.file, anchor=s.anchor,
                        body=s.body, run=s.run, expected=s.expected))
    return tuple(out)


class Planner(AgentNode):
    name = "planner"
    phase = Phase.PLANNING
    requires = (Requirement, CodeContext)
    produces = (Plan,)

    def __init__(self, llm: _LLMClientLike, project_map: ProjectMap) -> None:
        super().__init__(llm)
        self._map = project_map

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        req = effective_requirement(state)
        return [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"{render_position(self.name, state)}\n\n"
                    "REQUIREMENT:\n"
                    f"summary: {req.summary}\n"
                    f"acceptance:\n{self._bullets(req.acceptance)}\n"
                    f"out_of_scope:\n{self._bullets(req.out_of_scope)}\n"
                    f"assumptions:\n{self._bullets(req.assumptions)}\n"
                    f"open_questions:\n{self._bullets(req.open_questions)}\n\n"
                    f"GLOBAL ACCEPTANCE (your tasks must collectively satisfy these):\n"
                    f"{self._acceptance_digest(state)}\n\n"
                    f"CODE CONTEXT:\n{self._context_digest(state)}"
                    f"{self._repair_digest(state)}"
                ),
            },
        ]

    @staticmethod
    def _repair_digest(state: SessionState) -> str:
        if not state.repair_hint:
            return ""
        prior = state.plan
        tasks = "\n".join(
            f"  {t.id} [{', '.join(t.edit_scope.editable)}] {t.title}"
            for t in (prior.tasks if prior else ())
        ) or "  (none)"
        return (
            "\n\nSURGICAL REPAIR — your previous plan was REJECTED for this reason:\n"
            f"  {state.repair_hint}\n"
            "Fix ONLY the task named in that reason; keep every other task unchanged.\n"
            f"PRIOR PLAN (tasks):\n{tasks}\n"
        )

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
        # validate_output shape-coerces the weak-model deformation (e.g. tasks emitted
        # as {"task":[...]}) and wraps any failure as StructuredOutputError — never a
        # raw ValidationError, which used to crash the whole run with repair count 0.
        out = validate_output(_PlanOut, args_json, node=self.name)
        resolved = [(t, (t.id or f"t{i}")) for i, t in enumerate(out.tasks, start=1)]
        tasks = tuple(
            Task(
                id=rid,
                title=t.title or rid,
                purpose=t.purpose or "",
                edit_scope=EditScope(editable=tuple(dict.fromkeys(p for p in t.editable if p))),
                how_to_validate=t.how_to_validate or "",
                steps=_coerce_steps(t.steps, rid),
            )
            for t, rid in resolved
        )
        # id_map resolves a model-emitted raw id (possibly blank) to the canonical
        # resolved id, so depends_on references are consistent with Task.id values.
        id_map = {t.id: rid for t, rid in resolved}
        deps = tuple(
            Dependency(task_id=rid, depends_on=id_map.get(dep, dep))
            for t, rid in resolved
            for dep in t.depends_on
            if dep
        )
        file_plan = tuple(
            FileSlot(path=f.path, responsibility=f.responsibility)
            for f in out.file_plan if f.path
        )
        return Plan(tasks=tasks, deps=deps, file_plan=file_plan, plan_md=out.plan_md)

    @staticmethod
    def _bullets(items: tuple[str, ...]) -> str:
        if not items:
            return "  (none)"
        return "\n".join(f"  - {item}" for item in items)

    @staticmethod
    def _acceptance_digest(state: SessionState) -> str:
        spec = state.acceptance
        if spec is None or not spec.checks:
            return "  (none)"
        return "\n".join(f"  - ({c.criterion}) {c.command}" for c in spec.checks)

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
        if cc.environment:
            lines.append(
                "ENVIRONMENT — you MUST pick a stack/runtime listed as present below. "
                "Anything under 'NOT FOUND' is absent; a task that depends on it WILL fail "
                "(e.g. do not plan a Node server if node is NOT FOUND but python3 is "
                f"present):\n{cc.environment}")
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
            clipped = len(ex.text) > 600
            body = ex.text[:600] + " …" if clipped else ex.text
            label = " (truncated)" if ex.truncated or clipped else ""
            lines.append(f"--- {ex.path}{label} ---\n{body}")
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
