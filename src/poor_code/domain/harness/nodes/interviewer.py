# src/poor_code/domain/harness/nodes/interviewer.py
"""Interviewer — last node of the understanding layer. Single-step: each run
asks ONE Query (→ Driver suspends via NodeResult.query) or emits the Requirement
(→ done, route forwards to planner). The multi-round interview is the Driver
re-entering this node across suspend/resume turns; the loop's state lives in
SessionState.interview/pending_query, not in a loop here. Adversarial
spec-reviewer persona; asks only decision-changing questions; MAX_ROUNDS is a
hard code cap that overrides the model. See design.md §10/§19."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, StructuredOutputError, _LLMClientLike,
    MAX_DISPATCH_ATTEMPTS, validate_output,
)
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.session.models import (
    AnsweredQuery, CodeRef, GroundingStatus, Phase, Query, QueryKind, Requirement, SessionState,
)

_TOOL_NAME = "interview_step"
MAX_ROUNDS = 6

_SYSTEM = (
    "You are the Interviewer — a senior freelance engineer vetting an "
    "underspecified spec before you commit to building it. Be relentlessly "
    "skeptical: surface ambiguity, hidden assumptions, missing acceptance "
    "criteria, scope boundaries, edge/failure cases, and conflicts with the "
    "existing code shown in CODE CONTEXT (cite the candidate signatures). "
    "Always probe HOW the result will be validated (tests/commands/observable "
    "behavior). DISCIPLINE: ask ONLY a question whose answer would change what "
    "gets built — no filler, no nitpicking — and ask the single highest-leverage "
    "gap each round. When no decision-changing ambiguity remains, finish: emit "
    "the Requirement. Tone: blunt and direct, never personally insulting. "
    "Ground every question in CODE CONTEXT: cite the summary and file excerpts; if "
    "a needed file is not shown, do NOT invent its contents — record the gap in "
    "open_questions instead of guessing acceptance criteria. "
    "Ask in the user's language. Call interview_step exactly once."
)

_FINALIZE = (
    "\n\nYou have reached the question limit. Do NOT ask another question. "
    "Emit action=done with the best Requirement you can; put anything still "
    "unresolved into open_questions."
)


class _QueryOut(BaseModel):
    kind: Literal["clarify", "choose", "approve", "confirm"] = "clarify"
    prompt: str
    context: str | None = None
    options: list[str] = []
    resolves: str | None = None
    rationale: str = ""  # models routinely omit it; not worth failing a turn over


class _RequirementOut(BaseModel):
    summary: str = Field(min_length=1)
    acceptance: list[str] = []
    out_of_scope: list[str] = []
    assumptions: list[str] = []
    open_questions: list[str] = []


class _InterviewStepOut(BaseModel):
    action: Literal["ask", "done"]
    query: _QueryOut | None = None
    requirement: _RequirementOut | None = None


class Interviewer(AgentNode):
    name = "interviewer"
    phase = Phase.INTERVIEWING

    def __init__(self, llm: _LLMClientLike, project_map: ProjectMap,
                 tools: "ToolRegistry | None" = None) -> None:
        super().__init__(llm)
        self._map = project_map
        self._tools = tools

    async def run(self, ctx: NodeContext) -> NodeResult:
        state = ctx.state
        at_cap = len(state.interview) >= MAX_ROUNDS
        prev_raw = ""
        for attempt in range(MAX_DISPATCH_ATTEMPTS):
            extras: list[dict] | None = None
            if prev_raw:
                extras = [
                    {"role": "user", "content": (
                        f"Your previous reply was rejected. Re-emit a corrected "
                        f"interview_step call.\n\nprevious raw payload:\n{prev_raw}"
                    )},
                ]
            raw = await self._dispatch(ctx, extra_messages=extras)
            try:
                step = validate_output(_InterviewStepOut, raw, node=self.name)
                if step.action == "done" or at_cap:
                    if step.requirement is None:
                        raise StructuredOutputError(
                            self.name, raw,
                            "action='done' but requirement is None — supply a requirement object")
                    return NodeResult(output=self._to_requirement(step.requirement))
                if step.query is None:
                    raise StructuredOutputError(
                        self.name, raw,
                        "action='ask' but query is None — supply a query object with kind/prompt")
                qid = f"q{len(state.interview) + 1}"
                return NodeResult(query=self._to_query(qid, step.query))
            except StructuredOutputError as e:
                prev_raw = e.raw
                if attempt == MAX_DISPATCH_ATTEMPTS - 1:
                    raise

    def output_model(self) -> type[BaseModel]:
        return _InterviewStepOut

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        assert state.request is not None, "Interviewer requires state.request"
        system = _SYSTEM + (_FINALIZE if len(state.interview) >= MAX_ROUNDS else "")
        return [
            {"role": "system", "content": system},
            {"role": "user", "content":
                f"{render_position(self.name, state)}\n\n"
                f"REQUEST:\n{state.request.raw_text}\n\n"
                f"CODE CONTEXT:\n{self._context_digest(state)}\n\n"
                f"INTERVIEW SO FAR:\n{self._interview_digest(state.interview)}"},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": "Ask one question (action=ask) or finish (action=done).",
                "parameters": inline_refs(_InterviewStepOut.model_json_schema()),
            },
        }

    # --- mapping helpers ---
    @staticmethod
    def _to_query(qid: str, q: _QueryOut) -> Query:
        return Query(id=qid, kind=QueryKind(q.kind), prompt=q.prompt,
                     context=q.context, options=tuple(q.options),
                     resolves=q.resolves, rationale=q.rationale)

    @staticmethod
    def _to_requirement(r: _RequirementOut) -> Requirement:
        return Requirement(summary=r.summary, acceptance=tuple(r.acceptance),
                           out_of_scope=tuple(r.out_of_scope),
                           assumptions=tuple(r.assumptions),
                           open_questions=tuple(r.open_questions))

    # --- prompt digests ---
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
        for label, refs in (("candidates", cc.candidates),
                            ("confusers", cc.confusers),
                            ("related_tests", cc.related_tests)):
            lines.append(f"{label}:")
            if not refs:
                lines.append("  (none)")
            for r in refs:
                lines.append(f"  - {self._render_ref(r)}")
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
        for fe in self._map.files:
            if fe.path == ref.file:
                for s in fe.symbols:
                    if s.name == ref.symbol:
                        return s.signature
        return None

    @staticmethod
    def _interview_digest(interview: tuple[AnsweredQuery, ...]) -> str:
        if not interview:
            return "(none yet)"
        lines: list[str] = []
        for aq in interview:
            lines.append(f"Q({aq.query.kind.value}) {aq.query.prompt}")
            ans = aq.response.answer
            if aq.response.chosen_option:
                ans = f"[{aq.response.chosen_option}] {ans}"
            lines.append(f"  -> {ans}")
        return "\n".join(lines)
