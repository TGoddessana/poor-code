"""Router — classify the request. Conservative: ambiguous → engineering
(design.md §3). An AgentNode classifier (same shape as Locator) so non-English
and nuanced greetings route correctly; the deterministic prefix heuristic is kept
only as an offline/flake fallback when the model yields no structured output.
Owns no routing decision (that is route()); only sets kind."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output)
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import Phase, Request, RequestKind, SessionState

_TOOL_NAME = "classify_request"

_SYSTEM = (
    "You are the Router in a software-engineering harness. Classify the user "
    "request as 'engineering' (anything that touches code: features, bug fixes, "
    "refactors, design, code questions about THIS project) or 'lightweight' "
    "(greetings, small talk, thanks, generic questions unrelated to changing "
    "this codebase). When genuinely ambiguous, choose 'engineering' — skipping "
    "the engineering cycle is the dangerous direction. Reason briefly first, "
    "then call classify_request once. Language-agnostic: classify by intent, "
    "not by the language the user writes in."
)

_LIGHTWEIGHT_PREFIXES = ("hi", "hello", "hey", "thanks", "thank you", "?")


class _ClassificationOut(BaseModel):
    reason: str = ""
    kind: Literal["engineering", "lightweight"]


class Router(AgentNode):
    name = "router"
    phase = Phase.ROUTING
    requires = (Request,)
    produces = (Request,)

    def __init__(self, llm: _LLMClientLike) -> None:
        super().__init__(llm)

    async def run(self, ctx: NodeContext) -> NodeResult:
        req = ctx.state.request
        assert req is not None, "Router requires state.request"
        kind = await self._classify_via_llm(ctx)
        if kind is None:  # model gave no usable output → deterministic fallback
            kind = self._classify_seed(req.raw_text)
        return NodeResult(output=Request(raw_text=req.raw_text, kind=kind), branch=kind.value)

    async def _classify_via_llm(self, ctx: NodeContext) -> RequestKind | None:
        try:
            args_json = await self._dispatch(ctx)
            kind = validate_output(_ClassificationOut, args_json, node=self.name).kind
        except Exception:  # noqa: BLE001 — any LLM/parse failure → seed fallback
            return None
        return RequestKind(kind)

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        assert state.request is not None, "Router requires state.request"
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"REQUEST:\n{state.request.raw_text}"},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": "Emit the request classification.",
                "parameters": inline_refs(_ClassificationOut.model_json_schema()),
            },
        }

    def output_model(self) -> type[BaseModel]:
        return _ClassificationOut

    @staticmethod
    def _classify_seed(text: str) -> RequestKind:
        """Deterministic seed — English-prefix heuristic. Fallback only."""
        t = text.strip().lower()
        if not t:
            return RequestKind.LIGHTWEIGHT
        if t.startswith(_LIGHTWEIGHT_PREFIXES):
            return RequestKind.LIGHTWEIGHT
        return RequestKind.ENGINEERING  # conservative default
