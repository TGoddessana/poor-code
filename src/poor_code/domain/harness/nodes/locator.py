# src/poor_code/domain/harness/nodes/locator.py
"""Locator — symbol-grounded candidate context. Reads ProjectMap + Request,
emits CodeContext (CodeRefs into the map). Structured output via a single
forced 'emit_code_context' tool whose schema is _CodeContextOut (pydantic);
parsed into the frozen CodeContext domain object."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import AgentNode, _LLMClientLike, validate_output
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import CodeContext, CodeRef, SessionState

_TOOL_NAME = "emit_code_context"

_SYSTEM = (
    "You are the Locator in a software-engineering harness. Given a user request "
    "and a map of the codebase, identify the symbols/files most likely relevant "
    "(candidates), files that look related but are NOT (confusers), and related "
    "tests. Ground every reference in the provided map. Call emit_code_context once."
)


class _CodeRefOut(BaseModel):
    file: str
    symbol: str | None = None
    lineno: int | None = None


class _CodeContextOut(BaseModel):
    candidates: list[_CodeRefOut] = []
    confusers: list[_CodeRefOut] = []
    related_tests: list[_CodeRefOut] = []


class Locator(AgentNode):
    name = "locator"

    def __init__(self, llm: _LLMClientLike, project_map: ProjectMap) -> None:
        super().__init__(llm)
        self._map = project_map

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        assert state.request is not None, "Locator requires state.request"
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content":
                f"REQUEST:\n{state.request.raw_text}\n\nCODE MAP:\n{self._map_digest()}"},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": "Emit the symbol-grounded candidate context.",
                "parameters": _CodeContextOut.model_json_schema(),
            },
        }

    def parse(self, args_json: str) -> CodeContext:
        out = validate_output(_CodeContextOut, args_json, node=self.name)
        to_ref = lambda r: CodeRef(file=r.file, symbol=r.symbol, lineno=r.lineno)
        return CodeContext(
            candidates=tuple(to_ref(r) for r in out.candidates),
            confusers=tuple(to_ref(r) for r in out.confusers),
            related_tests=tuple(to_ref(r) for r in out.related_tests),
        )

    def _map_digest(self) -> str:
        """Compact, symbol-grounded view: file → symbols. Keeps the prompt small."""
        lines: list[str] = []
        for fe in self._map.files:
            syms = ", ".join(s.name for s in fe.symbols) or "(no symbols)"
            lines.append(f"- {fe.path} [{fe.language}]: {syms}")
        return "\n".join(lines)
