# src/poor_code/domain/harness/nodes/explorer.py
"""ExploringNode — understanding-layer node that READS file bodies. Replaces
Locator. Two stages: ① a read/grep tool loop over the codebase, then ② an
AgentNode-style emit_code_context extraction over the whole exploration history.
Empty result writes self-diagnosis into CodeContext.search_notes for repair."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from poor_code.domain.harness.env_probe import probe_environment
from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output,
)
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.project_map.models import FileEntry, ProjectMap
from poor_code.domain.session.models import (
    CodeContext, CodeRef, FileExcerpt, GroundingStatus, Phase, SessionState)
from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)
from poor_code.provider.usage import tag

_TOOL_NAME = "emit_code_context"
MAX_ITERATIONS = 20
MAX_EXCERPT_CHARS = 4000
HUB_IMPORTER_CAP = 8     # a file imported by more than this is a hub, not a receiver
MAX_RECEIVER_READS = 4   # total files the 1-hop augmentation round may read

_EXPLORE_SYSTEM = (
    "You are the Explorer, the codebase-reconnaissance step of a larger pipeline. "
    "Your ONLY job is to LOCATE the existing code relevant to the request by reading "
    "it firsthand. You do NOT answer the user, propose designs, suggest an "
    "implementation strategy, weigh options, or write any solution — later stages "
    "(interviewer, planner, implementer) do that. If you find yourself addressing the "
    "user or proposing what to build, stop: you are doing the wrong job.\n\n"
    "Work the tools well — exploration is your whole purpose. Use the cheap "
    "structured tools to find WHAT exists before searching contents:\n"
    "- `list` shows a directory's entries; `glob` finds files by pattern "
    "(e.g. '**/*.py'). Start there to map the project, then `read` files and "
    "`grep` their contents. Do NOT use grep over '**/*' as a way to list files — "
    "use list/glob for that.\n"
    "- The CODE MAP is only an index of symbol names; you MUST open files to confirm "
    "what they actually contain.\n"
    "- Read BROADLY when there IS code. Open every plausibly-relevant file, follow its "
    "imports and call sites, and grep for related names, callers, and similar patterns.\n"
    "- A non-trivial request needs MANY reads across MULTIPLE files. Keep calling "
    "read/grep until you have traced the feature — entry points, the layers it touches, "
    "and the tests.\n\n"
    "FOLLOW THE RECEIVER: when a relevant file emits a Message/Event or is a UI "
    "component, you must find who consumes it. The CODE MAP's 'used by' line "
    "lists that file's importers (one hop up) — open the importer/parent that "
    "mounts the widget or handles its event (e.g. an `on_*`/`@on` handler). A "
    "child widget alone is half the picture; the receiver is where submit/handler "
    "behaviour lives.\n\n"
    "GREENFIELD: if `list`/`glob` on the project root show no existing code (an empty "
    "or near-empty working dir), this is a build-from-scratch task. STOP exploring "
    "immediately — there is nothing to confirm. Do NOT widen the search, do NOT look "
    "outside the working directory, do NOT keep grepping. Report that the repo is "
    "greenfield and finish.\n\n"
    "Do not write or modify anything. Emit no prose conclusions — just explore."
)

_EXTRACT_SYSTEM = (
    "You explored the codebase by reading files. From the exploration above, "
    "emit the symbols/files most likely relevant (candidates), lookalikes that "
    "are NOT (confusers), and related tests — grounded in what you actually read. "
    "Set `grounding` to classify the result: if you found relevant existing code, "
    "fill candidates (grounding may stay 'not_found'). If candidates is EMPTY, you "
    "MUST choose why: 'greenfield' when the task is create-from-scratch and there is "
    "no existing code to ground (an empty or unrelated CODE MAP is strong evidence); "
    "'not_found' when code that SHOULD exist could not be located — then write a "
    "precise search_notes diagnosis (what you searched, what was empty, where to look "
    "next). Also write `summary`: ONE paragraph of ONLY what you OBSERVED — what "
    "relevant code exists and what is missing. Do NOT state what the request requires, "
    "do NOT invent data facts (sizes/formats), and do NOT propose how to validate the "
    "result — later nodes (interviewer, acceptance_oracle, planner) own those. "
    "Do NOT retype file bodies; the harness "
    "attaches what you read. Call emit_code_context once."
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
    grounding: Literal["not_found", "greenfield"] = "not_found"
    summary: str = ""


class ExploringNode(AgentNode):
    name = "explorer"
    phase = Phase.LOCATING

    def __init__(self, llm: _LLMClientLike, project_map: ProjectMap, tools: ToolRegistry) -> None:
        super().__init__(llm)
        self._map = project_map
        self._tools = tools

    async def run(self, ctx: NodeContext) -> NodeResult:
        environment = await probe_environment(Path.cwd())
        history, excerpts = await self._explore(ctx, environment)
        args_json = await self._dispatch(ctx, extra_messages=history)
        return NodeResult(output=self.parse(args_json, excerpts, environment=environment))

    # stage ① — the read/grep tool loop
    async def _explore(self, ctx: NodeContext, environment: str = "") -> tuple[list[dict[str, Any]], tuple[FileExcerpt, ...]]:
        state = ctx.state
        assert state.request is not None, "ExploringNode requires state.request"
        hint = ""
        if state.repair_hint:
            hint = f"\n\nRE-SEARCH: previous exploration failed — {state.repair_hint}. Widen the search."
        env_block = f"\n\nENVIRONMENT (available OS/runtimes/tools):\n{environment}" if environment else ""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _EXPLORE_SYSTEM},
            {"role": "user", "content":
                f"{render_position(self.name, state)}\n\n"
                f"REQUEST:\n{state.request.raw_text}\n\nCODE MAP:\n{self._map_digest()}"
                f"{env_block}{hint}"},
        ]
        tool_ctx = ToolContext(
            turn_id="explore", cancel=ctx.cancel, cwd=Path.cwd(), ask=allow_all)
        excerpts: dict[str, FileExcerpt] = {}

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
                self._maybe_record_excerpt(name, args, output, excerpts)
                if ctx.sink is not None:
                    if output.startswith("ERROR:"):
                        ctx.sink.tool_failed(cid, output)
                    else:
                        ctx.sink.tool_finished(cid, output)
                # Full output recorded as an excerpt + shown via the sink; the re-sent
                # exploration transcript gets a clamped copy (FM4).
                messages.append({
                    "role": "tool", "tool_call_id": cid,
                    "content": clamp_tool_output(output),
                })
        await self._pull_receivers(excerpts, tool_ctx, ctx)
        # hand the whole exploration (minus its own system prompt) to stage ②
        return messages[1:], tuple(excerpts.values())

    async def _stream_round(self, messages: list[dict[str, Any]], sink: object | None = None):
        text = ""
        pending: dict[str, dict[str, str]] = {}
        order: list[str] = []
        tag(self._llm, self.name)   # attribute this call's tokens to the explorer
        async for ev in self._llm.stream(messages=messages, tools=self._tools.schemas()):
            match ev:
                case TextDelta(text=t):
                    text += t   # keep accumulator for parsing; do NOT leak to UI
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

    @staticmethod
    def _maybe_record_excerpt(name: str, args_json: str, output: str,
                              excerpts: dict[str, FileExcerpt]) -> None:
        """Capture `read` tool outputs as ground-truth excerpts (last read of a
        path wins). grep results and tool errors are not file bodies → skipped."""
        if name != "read" or output.startswith("ERROR:"):
            return
        try:
            path = json.loads(args_json or "{}").get("path")
        except (ValueError, TypeError):
            path = None
        if not path:
            return
        text, truncated = output, False
        if len(text) > MAX_EXCERPT_CHARS:
            text, truncated = text[:MAX_EXCERPT_CHARS], True
        excerpts[path] = FileExcerpt(path=path, text=text, truncated=truncated)

    def _file_entry(self, path: str) -> FileEntry | None:
        return next((fe for fe in self._map.files if fe.path == path), None)

    async def _pull_receivers(
        self, excerpts: dict[str, FileExcerpt],
        tool_ctx: ToolContext, ctx: NodeContext,
    ) -> None:
        """Deterministic 1-hop coverage: read the importers (receivers) of the
        files the model read, so a child widget's parent/handler lands in the
        handoff memo even when the model stopped before opening it. Bounded
        (hub cut + total cap) to keep the downstream interviewer short-context."""
        seeds = list(excerpts)   # snapshot before we add anything: 1-hop, never 2-hop
        queued: list[str] = []
        for path in seeds:
            fe = self._file_entry(path)
            if fe is None or not fe.imported_by:
                continue
            if len(fe.imported_by) > HUB_IMPORTER_CAP:
                continue   # hub (app/models): its importers are not a single receiver
            for parent in fe.imported_by:
                if parent not in excerpts and parent not in queued:
                    queued.append(parent)
        for parent in queued[:MAX_RECEIVER_READS]:
            if ctx.cancel.is_set():
                break
            cid = f"1hop:{parent}"
            args = json.dumps({"path": parent})
            if ctx.sink is not None:
                ctx.sink.tool_started(cid, "read", {"path": parent})
            output = await self._run_tool("read", args, tool_ctx)
            self._maybe_record_excerpt("read", args, output, excerpts)
            if ctx.sink is not None:
                if output.startswith("ERROR:"):
                    ctx.sink.tool_failed(cid, output)
                else:
                    ctx.sink.tool_finished(cid, output)

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
                "parameters": inline_refs(_CodeContextOut.model_json_schema()),
            },
        }

    def output_model(self) -> type[BaseModel]:
        return _CodeContextOut

    def parse(self, args_json: str, excerpts: tuple[FileExcerpt, ...] = (),
              environment: str = "") -> CodeContext:
        out = validate_output(_CodeContextOut, args_json, node=self.name)
        to_ref = lambda r: CodeRef(file=r.file, symbol=r.symbol, lineno=r.lineno)
        grounding = GroundingStatus(out.grounding)
        # Deterministic safety net: an empty working tree (no files in the project
        # map) with no candidates is unambiguously greenfield, whatever the model
        # guessed. The model kept labelling an empty repo 'not_found', which made
        # the UnderstandingGate bounce then escalate -> ABANDONED before planning.
        if (not out.candidates and not self._map.files
                and grounding is GroundingStatus.NOT_FOUND):
            grounding = GroundingStatus.GREENFIELD
        return CodeContext(
            candidates=tuple(to_ref(r) for r in out.candidates),
            confusers=tuple(to_ref(r) for r in out.confusers),
            related_tests=tuple(to_ref(r) for r in out.related_tests),
            search_notes=out.search_notes,
            grounding=grounding,
            summary=out.summary,
            excerpts=excerpts,
            environment=environment,
        )

    def _map_digest(self) -> str:
        lines: list[str] = []
        for fe in self._map.files:
            syms = ", ".join(s.name for s in fe.symbols) or "(no symbols)"
            lines.append(f"- {fe.path} [{fe.language}]: {syms}")
            if fe.imported_by:
                lines.append(f"    ← used by: {', '.join(fe.imported_by)}")
        return "\n".join(lines)


def _safe_args(args_json: str) -> dict:
    try:
        v = json.loads(args_json or "{}")
        return v if isinstance(v, dict) else {"_": v}
    except (ValueError, TypeError):
        return {}
