# src/poor_code/domain/harness/nodes/explorer.py
"""ExploringNode — understanding-layer node that READS file bodies. Replaces
Locator. Two stages: ① a read/grep tool loop over the codebase, then ② an
AgentNode-style emit_code_context extraction over the whole exploration history.
Empty result writes self-diagnosis into CodeContext.search_notes for repair."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import AgentNode, NodeContext, NodeResult, _LLMClientLike
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import CodeContext, CodeRef, SessionState
from poor_code.domain.tool.registry import ToolRegistry

_TOOL_NAME = "emit_code_context"

_EXTRACT_SYSTEM = (
    "You explored the codebase by reading files. From the exploration above, "
    "emit the symbols/files most likely relevant (candidates), lookalikes that "
    "are NOT (confusers), and related tests — grounded in what you actually read. "
    "If you found nothing, leave candidates empty and write a precise search_notes "
    "diagnosis (what you searched, what was empty, where to look next). "
    "Call emit_code_context once."
)


class _CodeRefOut(BaseModel):
    file: str
    symbol: str | None = None
    lineno: int | None = None


class _CodeContextOut(BaseModel):
    candidates: list[_CodeRefOut] = []
    confusers: list[_CodeRefOut] = []
    related_tests: list[_CodeRefOut] = []
    search_notes: str = ""


class ExploringNode(AgentNode):
    name = "explorer"

    def __init__(self, llm: _LLMClientLike, project_map: ProjectMap, tools: ToolRegistry) -> None:
        super().__init__(llm)
        self._map = project_map
        self._tools = tools

    async def run(self, ctx: NodeContext) -> NodeResult:
        history = await self._explore(ctx)
        args_json = await self._dispatch(ctx, extra_messages=history)
        return NodeResult(output=self.parse(args_json))

    # stage ① — stubbed for now (Task 6 fills the tool loop)
    async def _explore(self, ctx: NodeContext) -> list[dict[str, Any]]:
        return []

    # stage ② — extraction (build_messages provides system+user envelope)
    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": "Emit the CodeContext for the exploration above."},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": "Emit the body-grounded code context.",
                "parameters": _CodeContextOut.model_json_schema(),
            },
        }

    def parse(self, args_json: str) -> CodeContext:
        out = _CodeContextOut.model_validate_json(args_json)
        to_ref = lambda r: CodeRef(file=r.file, symbol=r.symbol, lineno=r.lineno)
        return CodeContext(
            candidates=tuple(to_ref(r) for r in out.candidates),
            confusers=tuple(to_ref(r) for r in out.confusers),
            related_tests=tuple(to_ref(r) for r in out.related_tests),
            search_notes=out.search_notes,
        )

    def _map_digest(self) -> str:
        lines: list[str] = []
        for fe in self._map.files:
            syms = ", ".join(s.name for s in fe.symbols) or "(no symbols)"
            lines.append(f"- {fe.path} [{fe.language}]: {syms}")
        return "\n".join(lines)
