"""acceptance_oracle — designs the GLOBAL, plan-independent acceptance check (the
authoritative 'done'). Reads only the binding Requirement (+ CodeContext as
reference); never the plan. Emits a runnable AcceptanceSpec via one tool call."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import AgentNode, _LLMClientLike
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, GroundingStatus, SessionState,
    effective_requirement,
)

_TOOL_NAME = "emit_acceptance"

_SYSTEM = (
    "You are the Acceptance Oracle. From the binding REQUIREMENT (CODE CONTEXT is "
    "reference only), design the GLOBAL acceptance check — the authoritative, runnable "
    "definition of 'done'. You do NOT see or design the implementation plan; you decide "
    "ONLY how we will KNOW the result is correct.\n"
    "RULES:\n"
    "1. Each check is a RUNNABLE shell command; exit 0 means its criterion holds. Map "
    "each check to one acceptance criterion.\n"
    "2. Prefer CONTENT / BEHAVIOR equality over derived metrics. To check exact file "
    "content use `printf '%s' \"$EXPECTED\" | diff - file` or a literal grep — NOT a byte "
    "count like `wc -c == N`.\n"
    "3. NEVER assert a size/count/digest you did not obtain by actually running a command, "
    "and NEVER hard-code a guessed integer. Derive expected at run time, e.g. "
    "`expected=$(printf '%s' \"$S\" | wc -c)`.\n"
    "4. Observe REAL behavior (start the thing, curl it), never a surface string. A check "
    "that starts a long-running process MUST kill it and exit with the check's status.\n"
    "ANTI-GAMING INVARIANTS (apply to EVERY task — a check that violates these will be "
    "rejected by an adversarial critic):\n"
    "5. EXACT equality, never SUBSTRING. Match the whole value: `test \"$got\" = \"$want\"`, "
    "`grep -qx`, or `diff`. A check like `grep -q '\"result\":5'` is BROKEN — it also passes "
    "on 55 or 500.\n"
    "6. Defend against a LOOKUP-TABLE / hard-coded implementation: do NOT only check inputs "
    "named in the requirement or its examples. Include AT LEAST ONE input the requirement "
    "never mentions, whose expected output you DERIVE at run time — so an impl that hard-codes "
    "the example answers cannot pass.\n"
    "7. Include AT LEAST ONE boundary / extreme input (empty, zero, negative, very large, or "
    "malformed) where a naive or hard-coded implementation would diverge from a correct one.\n"
    "Call emit_acceptance once."
)


class _AcceptanceCheckOut(BaseModel):
    criterion: str
    command: str
    rationale: str = ""


class _AcceptanceSpecOut(BaseModel):
    checks: list[_AcceptanceCheckOut] = []


class AcceptanceOracle(AgentNode):
    name = "acceptance_oracle"

    def __init__(self, llm: _LLMClientLike) -> None:
        super().__init__(llm)

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        req = effective_requirement(state)
        prior = ""
        if state.repair_hint:
            prior = (
                "PRIOR REJECTION — the adversarial critic BROKE your previous acceptance "
                "design with the COUNTEREXAMPLE below (a wrong implementation that still "
                "passed, or a correct one that failed). Your redesigned checks MUST make "
                "this counterexample FAIL; do NOT resubmit checks it would still pass. "
                "Address the specific hole it exposes (e.g. switch substring matches to "
                "exact equality, add an input the examples never cover).\n"
                f"<<< COUNTEREXAMPLE\n{state.repair_hint}\n>>>\n\n")
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"{prior}"
                "REQUIREMENT:\n"
                f"summary: {req.summary}\n"
                f"acceptance:\n{self._bullets(req.acceptance)}\n"
                f"out_of_scope:\n{self._bullets(req.out_of_scope)}\n"
                f"assumptions:\n{self._bullets(req.assumptions)}\n\n"
                f"CODE CONTEXT:\n{self._context_digest(state)}")},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Emit the global acceptance checks.",
                             "parameters": inline_refs(_AcceptanceSpecOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _AcceptanceSpecOut

    def parse(self, args_json: str) -> AcceptanceSpec:
        out = _AcceptanceSpecOut.model_validate_json(args_json)
        return AcceptanceSpec(checks=tuple(
            AcceptanceCheck(criterion=c.criterion, command=c.command, rationale=c.rationale)
            for c in out.checks))

    @staticmethod
    def _bullets(items: tuple[str, ...]) -> str:
        if not items:
            return "  (none)"
        return "\n".join(f"  - {item}" for item in items)

    @staticmethod
    def _context_digest(state: SessionState) -> str:
        cc = state.understanding
        if cc is None:
            return "(none)"
        lines: list[str] = []
        if cc.grounding is GroundingStatus.GREENFIELD:
            lines.append("MODE: greenfield (create-from-scratch; no existing code to ground).")
        if cc.summary:
            lines.append(f"summary: {cc.summary}")
        return "\n".join(lines) if lines else "(none)"
