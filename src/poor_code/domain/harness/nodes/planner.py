# src/poor_code/domain/harness/nodes/planner.py
"""Planner — converts a binding Requirement into bounded implementation tasks.

This is still a thin AgentNode: it does not inspect file bodies or execute tools.
It receives Requirement as binding input and CodeContext as reference material,
then emits a Plan through one structured-output tool call.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from poor_code.domain.harness.node import AgentNode, _LLMClientLike, validate_output
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import (
    CodeRef,
    Dependency,
    EditScope,
    FileSlot,
    GroundingStatus,
    Phase,
    Plan,
    SessionState,
    Step,
    StepKind,
    Task,
    effective_requirement,
)

_TOOL_NAME = "emit_plan"


def _derive_editable(task: "_TaskOut") -> tuple[str, ...]:
    """FM1 — compute a task's editable scope in CODE rather than trusting the weak
    model to keep edit_scope.editable in sync with its steps. A CREATE task names the
    new file in its steps but routinely omits it from editable, which made plan_gate's
    `step.file not in editable` reject every create-from-scratch task (openssl, org
    json, greenfield). editable = declared editable ∪ the files this task's own steps
    write (deterministic, per-task, order-preserving, deduped). The gate stays dumb."""
    editable: list[str] = []
    for path in (*task.edit_scope.editable, *(s.file for s in task.steps)):
        if path and path not in editable:
            editable.append(path)
    return tuple(editable)

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
    "AUDIENCE: the engineer who executes this plan is WEAK and LITERAL. If you do not "
    "write the code, they will write it wrong. Spell everything out.\n"
    "PREAMBLE (before the tool call, in 2-3 sentences MAX, then STOP): state the "
    "approach and list the files you will touch. Do not ramble.\n"
    "STEPS: every task carries an ordered `steps` list. Each step is one action with: "
    "kind (test|impl|run), file, anchor (where in the file), body (the ACTUAL code as "
    "a single string), run (the exact command), expected (PASS | FAIL: <substr> | a "
    "grep token). A test/impl step MUST have a non-empty body. Show the real code — "
    "NO empty bodies.\n"
    "NO PLACEHOLDERS — these make a step INVALID: 'TODO', 'TBD', 'fill in later', "
    "'implement later', 'add appropriate error handling', 'handle edge cases', "
    "'similar to task N', or referencing a symbol no step defines.\n"
    "GROUNDING: build only on the symbols/anchors in CODE CONTEXT. DO NOT INVENT APIs, "
    "modules, or functions that are not shown to exist.\n"
    "STEP EXAMPLE — fixing a bug in foo.py:\n"
    "  step1 kind=test file=tests/test_foo.py anchor='end of file'\n"
    "    body: 'def test_bar():\\n    assert bar(2) == 4'\n"
    "    run: 'pytest tests/test_foo.py::test_bar -q'  expected: 'PASS'\n"
    "  step2 kind=impl file=foo.py anchor='def bar (line 12)'\n"
    "    body: 'def bar(x):\\n    return x * 2'\n"
    "    run: 'pytest tests/test_foo.py::test_bar -q'  expected: 'PASS'\n"
    "Call emit_plan once."
)


class _EditScopeOut(BaseModel):
    editable: list[str] = []
    readonly: list[str] = []
    forbidden: list[str] = []


class _StepOut(BaseModel):
    kind: str = "impl"
    file: str = ""
    anchor: str = ""
    body: str = ""
    run: str = ""
    expected: str = ""


_STEP_KIND = {"test": StepKind.TEST, "impl": StepKind.IMPL, "run": StepKind.RUN}


class _TaskOut(BaseModel):
    title: str
    purpose: str
    description: str = ""
    edit_scope: _EditScopeOut = Field(default_factory=_EditScopeOut)
    how_to_validate: str = ""
    steps: list[_StepOut] = []


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
    phase = Phase.PLANNING

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
        # validate_output shape-coerces the weak-model deformation (e.g. steps emitted
        # as {"step":[...]}) and wraps any failure as StructuredOutputError — never a
        # raw ValidationError, which used to crash the whole run with repair count 0.
        out = validate_output(_PlanOut, args_json, node=self.name)
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
        task_id = f"t{index}"
        steps = tuple(
            Step(
                id=f"{task_id}.s{j}",
                kind=_STEP_KIND.get(step.kind.strip().lower(), StepKind.IMPL),
                file=step.file,
                anchor=step.anchor,
                body=step.body,
                run=step.run,
                expected=step.expected,
            )
            for j, step in enumerate(task.steps, start=1)
        )
        return Task(
            id=task_id,
            title=task.title,
            purpose=task.purpose,
            description=task.description,
            edit_scope=EditScope(
                editable=_derive_editable(task),
                readonly=tuple(task.edit_scope.readonly),
                forbidden=tuple(task.edit_scope.forbidden),
            ),
            how_to_validate=task.how_to_validate,
            steps=steps,
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
