"""Router — classify the request. Conservative: ambiguous → engineering
(design.md §3). v1 heuristic is a deterministic seed; replace with an LLM
classifier later. Owns no routing decision (that is route()); only sets kind."""
from __future__ import annotations

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.session.models import Request, RequestKind

_LIGHTWEIGHT_PREFIXES = ("hi", "hello", "hey", "thanks", "thank you", "?")


class Router:
    name = "router"

    async def run(self, ctx: NodeContext) -> NodeResult:
        req = ctx.state.request
        assert req is not None, "Router requires state.request"
        kind = self._classify(req.raw_text)
        return NodeResult(output=Request(raw_text=req.raw_text, kind=kind))

    @staticmethod
    def _classify(text: str) -> RequestKind:
        t = text.strip().lower()
        if not t:
            return RequestKind.LIGHTWEIGHT
        if t.startswith(_LIGHTWEIGHT_PREFIXES):
            return RequestKind.LIGHTWEIGHT
        return RequestKind.ENGINEERING  # conservative default
