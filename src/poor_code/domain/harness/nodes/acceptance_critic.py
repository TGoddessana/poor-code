"""acceptance_critic — adversarial review of the AcceptanceSpec. Tries to BREAK the
checks: find a wrong implementation that still passes, or a correct one that fails.
Catches the task-DEPENDENT semantic holes a deterministic gate provably cannot
(e.g. `grep -q Hello` passing on 'Hello, mars!'). Emits a Verdict, not output."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output,
)
from poor_code.domain.harness.nodes.gates import _acceptance_repair_count
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    Layer, SessionState, Verdict, VerdictKind,
)

_TOOL_NAME = "emit_critique"
_REPAIR_BUDGET = 2

_SYSTEM = (
    "You are the Acceptance Critic. Try to BREAK the proposed acceptance checks. Produce "
    "EITHER (a) a WRONG implementation that still passes EVERY check, OR (b) a CORRECT "
    "implementation that FAILS some check. If you can produce either, the checks are "
    "INADEQUATE: set adequate=false and put the concrete counterexample in counterexample. "
    "Only if you genuinely cannot break them, set adequate=true. Default to skepticism — "
    "watch for checks that pass on near-misses (wrong content, missing trailing newline, "
    "surface string match). Call emit_critique once."
)


class _CritiqueOut(BaseModel):
    adequate: bool
    counterexample: str | None = None


class AcceptanceCritic(AgentNode):
    name = "acceptance_critic"

    def __init__(self, llm: _LLMClientLike) -> None:
        super().__init__(llm)

    async def run(self, ctx: NodeContext) -> NodeResult:
        out = validate_output(_CritiqueOut, await self._dispatch(ctx), node=self.name)
        if out.adequate:
            return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
        hint = out.counterexample or "Acceptance checks are inadequate; redesign."
        if _acceptance_repair_count(ctx.state) >= _REPAIR_BUDGET:
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ESCALATE,
                query=f"Acceptance checks still inadequate after redesign: {hint}"))
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.ACCEPTANCE, hint=hint))

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        req = state.requirement
        spec = state.acceptance
        checks = "\n".join(
            f"  - ({c.criterion}) {c.command}" for c in (spec.checks if spec else ())
        ) or "  (none)"
        summary = req.summary if req is not None else "(no requirement)"
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"REQUIREMENT summary: {summary}\n\n"
                f"PROPOSED ACCEPTANCE CHECKS:\n{checks}")},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Report whether the acceptance checks are adequate.",
                             "parameters": inline_refs(_CritiqueOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _CritiqueOut

    def parse(self, args_json: str) -> object:  # unused; run() handles verdict inline
        return _CritiqueOut.model_validate_json(args_json)
