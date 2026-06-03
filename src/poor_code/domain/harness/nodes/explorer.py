# src/poor_code/domain/harness/nodes/explorer.py
"""ExploringNode — understanding-layer node that READS file bodies. Replaces
Locator. Two stages: ① a read/grep tool loop over the codebase, then ② an
AgentNode-style emit_code_context extraction over the whole exploration history.
Empty result writes self-diagnosis into CodeContext.search_notes for repair."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output,
)
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import CodeContext, CodeRef, SessionState
from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)

_TOOL_NAME = "emit_code_context"
MAX_ITERATIONS = 8

_EXPLORE_SYSTEM = (
    "You are the Explorer, the codebase-reconnaissance step of a larger pipeline. "
    "Your ONLY job is to LOCATE the existing code relevant to the request by reading "
    "it firsthand. You do NOT answer the user, propose designs, suggest an "
    "implementation strategy, weigh options, or write any solution — later stages "
    "(interviewer, planner, implementer) do that. If you find yourself addressing the "
    "user or proposing what to build, stop: you are doing the wrong job.\n\n"
    "Work the tools hard — exploration is your whole purpose:\n"
    "- The CODE MAP is only an index of symbol names; you MUST open files to confirm "
    "what they actually contain.\n"
    "- Read BROADLY. One file is almost never enough. Open every plausibly-relevant "
    "file, follow its imports and call sites, and grep for related names, callers, "
    "and similar patterns across the tree.\n"
    "- A non-trivial request (new subsystems, cross-cutting features) needs MANY reads "
    "across MULTIPLE files. Keep calling read/grep until you have actually traced the "
    "feature through the code — entry points, the layers it touches, and the tests.\n"
    "- Only stop calling tools once you have confirmed the relevant code by reading it, "
    "not after a single glance.\n\n"
    "Do not write or modify anything. Emit no prose conclusions — just explore."
)

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

    # stage ① — the read/grep tool loop
    async def _explore(self, ctx: NodeContext) -> list[dict[str, Any]]:
        state = ctx.state
        assert state.request is not None, "ExploringNode requires state.request"
        hint = ""
        if state.repair_hint:
            hint = f"\n\nRE-SEARCH: previous exploration failed — {state.repair_hint}. Widen the search."
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _EXPLORE_SYSTEM},
            {"role": "user", "content":
                f"REQUEST:\n{state.request.raw_text}\n\nCODE MAP:\n{self._map_digest()}{hint}"},
        ]
        tool_ctx = ToolContext(
            turn_id="explore", cancel=ctx.cancel, cwd=Path.cwd(), ask=allow_all)

        for _ in range(MAX_ITERATIONS):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            text, calls = await self._stream_round(messages, ctx.sink)
            assistant: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                assistant["tool_calls"] = [
                    {"id": cid, "type": "function",
                     "function": {"name": name, "arguments": args or "{}"}}
                    for cid, name, args in calls
                ]
            messages.append(assistant)
            if not calls:
                break
            for cid, name, args in calls:
                if ctx.sink is not None:
                    ctx.sink.tool_started(cid, name, _safe_args(args))
                output = await self._run_tool(name, args, tool_ctx)
                if ctx.sink is not None:
                    if output.startswith("ERROR:"):
                        ctx.sink.tool_failed(cid, output)
                    else:
                        ctx.sink.tool_finished(cid, output)
                messages.append({
                    "role": "tool", "tool_call_id": cid, "content": output,
                })
        # hand the whole exploration (minus its own system prompt) to stage ②
        return messages[1:]

    async def _stream_round(self, messages: list[dict[str, Any]], sink: object | None = None):
        text = ""
        pending: dict[str, dict[str, str]] = {}
        order: list[str] = []
        async for ev in self._llm.stream(messages=messages, tools=self._tools.schemas()):
            match ev:
                case TextDelta(text=t):
                    text += t
                    if sink is not None:
                        sink.text_delta(t)
                case ToolCallStarted(call_id=cid, name=name):
                    pending[cid] = {"name": name, "args": ""}
                    order.append(cid)
                case ToolCallInputDelta(call_id=cid, json_delta=d):
                    if cid in pending:
                        pending[cid]["args"] += d
                case ToolCallEnded() | FinishedReason():
                    pass
        return text, [(cid, pending[cid]["name"], pending[cid]["args"]) for cid in order]

    async def _run_tool(self, name: str, args_json: str, tool_ctx: ToolContext) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"ERROR: unknown tool {name}"
        try:
            parsed = tool.params.model_validate_json(args_json or "{}")
            result = await tool.execute(parsed, tool_ctx)
            return result.output
        except Exception as e:  # noqa: BLE001 — tool errors feed back to the model
            return f"ERROR: {type(e).__name__}: {e}"

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
        out = validate_output(_CodeContextOut, args_json, node=self.name)
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


def _safe_args(args_json: str) -> dict:
    try:
        v = json.loads(args_json or "{}")
        return v if isinstance(v, dict) else {"_": v}
    except (ValueError, TypeError):
        return {}
