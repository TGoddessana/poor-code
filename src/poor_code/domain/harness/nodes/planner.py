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
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import (
    CodeRef,
    Dependency,
    EditScope,
    FileSlot,
    GroundingStatus,
    Plan,
    SessionState,
    Task,
    effective_requirement,
)

_TOOL_NAME = "emit_plan"

_SYSTEM = (
    "You are the Planner. Convert the binding Requirement into the SMALLEST set of "
    "PATCH-SIZED engineering Tasks that delivers it.\n"
    "FILE PLAN FIRST: before any task, fill file_plan — every file this change "
    "touches and that file's single responsibility. Then derive tasks FROM "
    "file_plan. Every task's edit_scope.editable MUST be a file named in file_plan. "
    "Never emit a task for a file that does not belong to the chosen stack "
    "(e.g. no package.json in a Python project).\n"
    "RULES:\n"
    "1. One task = one patch with one primary editable file (2-3 max). Group by "
    "RESPONSIBILITY: files that CHANGE TOGETHER belong in the SAME task. Do NOT "
    "split 'write the test' from 'implement it' — they are ONE task. A single "
    "deliverable (one bug fix, one server) is ONE task. Default to FEWER tasks; "
    "split only when two parts are INDEPENDENTLY SHIPPABLE. When unsure, MERGE.\n"
    "2. Every task MUST have a non-empty edit_scope.editable and a how_to_validate "
    "that is a RUNNABLE COMMAND (not prose). The ValidationRunner executes that "
    "string literally and checks its exit code — 'Check that ...' is invalid; an "
    "actual command is required.\n"
    "3. Validation must observe real, observable behavior, not a surface string. "
    "Bad: assert package.json scripts.start == 'node server.js'. "
    "Good: curl a real response from the running service.\n"
    ">>> 3a. MUST-FAIL-FIRST (CRITICAL): how_to_validate MUST FAIL on the CURRENT, "
    "unfixed code and pass ONLY AFTER your change — it has to exercise the ACTUAL bug. "
    "A validation that already passes before the fix is BROKEN and worthless. If the "
    "Requirement carries a reproduction snippet, run THAT EXACT snippet as the validation. "
    "NEVER use a selector that can match zero tests and pass trivially (e.g. `pytest -k "
    "<name>` with no guarantee a matching test exists) — prefer a direct repro "
    "(python -c '...' / node -e '...') that asserts the corrected behavior and exits "
    "non-zero on today's code. <<<\n"
    "4. Use ids t1, t2, ... and order them by dependency. New files go in "
    "edit_scope.editable.\n"
    "5. Long-running services (servers/daemons): the IMPLEMENTER launches the service "
    "and LEAVES IT RUNNING — it must outlive this run. Do NOT write start-then-stop "
    "validation. how_to_validate is a BARE PROBE against the already-running service — "
    "no launch, no stop — e.g. curl -fs localhost:3000/fib?n=8 | grep -q '\"result\":21'.\n"
    "6. CodeContext (summary/excerpts) is reference material, not binding truth.\n"
    "7. A GLOBAL ACCEPTANCE spec defines 'done'. Your tasks together must satisfy it; "
    "keep each how_to_validate consistent with those checks.\n"
    "EXAMPLE — request 'Node HTTP server, GET /fib/:n -> nth Fibonacci (BigInt), :3000':\n"
    "  file_plan: lib/fib.js (pure nth Fibonacci), server.js (:3000 route /fib/:n)\n"
    "  t1 lib/fib.js (pure BigInt nth Fibonacci)\n"
    "     validate: node -e \"if(require('./lib/fib')(10)!==55n)process.exit(1)\"\n"
    "  t2 server.js (:3000, route /fib/:n; implementer launches it and leaves it "
    "running), depends on t1\n"
    "     validate: curl -fs localhost:3000/fib/10 | grep -qx 55\n"
    "Call emit_plan once."
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


class _FileSlotOut(BaseModel):
    path: str
    responsibility: str = ""


class _PlanOut(BaseModel):
    file_plan: list[_FileSlotOut] = []
    tasks: list[_TaskOut] = []
    deps: list[_DependencyOut] = []


class Planner(AgentNode):
    name = "planner"

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
        file_plan = tuple(
            FileSlot(path=slot.path, responsibility=slot.responsibility)
            for slot in out.file_plan
        )
        return Plan(tasks=tasks, deps=deps, file_plan=file_plan)

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
