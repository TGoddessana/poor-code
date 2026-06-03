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

# After this many bounces back to the oracle, accept the gate-valid spec and move
# on. "Can you break it?" is unbounded — a finite check set is ALWAYS theoretically
# gameable (hard-code the tested inputs), so without a stopping rule the critic
# loops forever. The bar below makes the common case converge in round 1; this cap
# is the backstop that guarantees forward progress over abandoning the run.
_CONVERGENCE_CAP = 3

_SYSTEM = (
    "You are the Acceptance Critic. Judge whether the proposed acceptance checks are "
    "ADEQUATE against a FINITE bar — NOT whether they are theoretically unbreakable.\n"
    "The checks are ADEQUATE (set adequate=true) when ALL of these hold:\n"
    "1. EXACT equality, not SUBSTRING: output values are matched in full "
    "(`test \"$x\" = \"$y\"`, `grep -qx`, `diff`), not via a substring that also passes on "
    "wrong values (e.g. `grep '\"result\":5'` also matches 55).\n"
    "2. At least ONE input NOT named in the requirement/examples, with its expected value "
    "derived at run time — so an implementation that hard-codes the example answers fails.\n"
    "3. At least ONE boundary / extreme input (empty, zero, negative, very large, malformed).\n"
    "If all three hold you MUST set adequate=true, even though a finite set of checks could "
    "in principle be gamed by a sufficiently elaborate hard-coded implementation. The mere "
    "facts that 'checks are finite', 'a lookup table could pass', or 'more inputs could be "
    "tested' are NOT grounds for rejection — do not reject on those.\n"
    "Set adequate=false ONLY when a check VIOLATES the bar — i.e. you can name a concrete "
    "wrong implementation that passes BECAUSE of a substring match, because only "
    "example/named inputs are tested, or because no boundary input is covered. Put that "
    "concrete counterexample, and which bar item it breaks, in counterexample. "
    "Call emit_critique once."
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
        # Convergence backstop: the gate has already confirmed the spec is well-formed
        # (runnable, non-prose, cwd-safe). Once we've redesigned CONVERGENCE_CAP times
        # and the critic still objects, accept it and proceed rather than loop to the
        # hard budget and abandon — "can you break a finite check set?" is unbounded.
        if _acceptance_repair_count(ctx.state) >= _CONVERGENCE_CAP:
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ADVANCE,
                hint=(f"accepted gate-valid acceptance spec after {_CONVERGENCE_CAP} "
                      f"redesigns; last (unmet) critic objection: {hint[:200]}")))
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
