"""provisioner — agentic env-prep [A]. Runs ONCE after plan approval and before the
implementation layer. terminal-bench task containers ship only source (no pytest, no
deps, no built C-extensions); without provisioning every validation dies 'pytest not
found' / 'No module named ...' and the model gets zero feedback to refine a near-correct
fix — and (observed) wastes its budget hand-faking stub modules to satisfy imports.

Two stages, modeled on the Explorer: ① a bash/read tool loop that detects the project's
build/test setup and actually installs it, then ② an emit_env_report extraction. The
resulting EnvReport is injected forward into the implementer so it does not re-discover
(or fake) the test setup. Best effort by contract: it NEVER fails the run — on a missing
structured report it falls back to a deterministic seed EnvReport (ready=False)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, StructuredOutputError, _LLMClientLike,
    validate_output,
)
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import EnvReport, SessionState
from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)

_TOOL_NAME = "emit_env_report"
MAX_ITERATIONS = 12

# Deterministic seed/fallback for a standard Python project — offered to the agent as a
# default and used verbatim when the agent cannot emit a structured report.
_ENSURE_CC = (
    "command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 || "
    "(apt-get update -qq && apt-get install -y -qq --no-install-recommends "
    "gcc g++ python3-dev) || true"
)
_EDITABLE_INSTALL = (
    "python -m pip install -q -e '.[test]' || "
    "python -m pip install -q -e '.[dev]' || "
    "python -m pip install -q -e . || true"
)
_ENSURE_PYTEST = "python -m pip install -q pytest || true"


def plan_commands(cwd: Path) -> list[str]:
    """Deterministic seed bootstrap commands for the project rooted at `cwd`. Empty
    when there is no Python project marker (greenfield / non-Python)."""
    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
        return [_ENSURE_CC, _EDITABLE_INSTALL, _ENSURE_PYTEST]
    return []


_PROVISION_SYSTEM = (
    "You are the Provisioner. Your ONE job: make THIS project's tests RUNNABLE so the "
    "later implementation step can validate its fix. The container ships only source — "
    "no dependencies, no pytest, no built C-extensions. Use bash to:\n"
    "1. detect the build/test setup (read pyproject.toml / setup.py / setup.cfg / "
    "tox.ini / Makefile / README / CI yml),\n"
    "2. install the project and its test deps the project's documented way (for a "
    "standard Python project: ensure a C compiler, then `python -m pip install -e "
    "'.[test]'`), \n"
    "3. VERIFY it worked by actually running the test runner (e.g. `python -m pytest "
    "--co -q` to collect, or run one test) and reading the result.\n"
    "RULES: Do NOT modify source code — you only set up the ENVIRONMENT. Do NOT write "
    "the fix. Keep calling bash until the test runner actually runs (imports resolve, "
    "pytest is found), then stop.\n"
    "A reasonable default sequence for a standard Python project:\n{seed}\n"
)

_REPORT_SYSTEM = (
    "From your provisioning work above, emit the EnvReport. Set `ready` true only if the "
    "test runner actually ran (pytest found, imports resolved). `test_command` is the "
    "canonical command to run this project's tests (e.g. 'python -m pytest -q'). "
    "`install_steps` are the commands you actually ran to bootstrap. `notes` records "
    "gotchas or what is still missing. Call emit_env_report once."
)


class _EnvReportOut(BaseModel):
    ready: bool = False
    test_command: str = ""
    install_steps: list[str] = []
    notes: str = ""


class Provisioner(AgentNode):
    name = "provisioner"

    def __init__(self, llm: _LLMClientLike, cwd: Path, tools: ToolRegistry) -> None:
        super().__init__(llm)
        self._cwd = cwd
        self._tools = tools

    async def run(self, ctx: NodeContext) -> NodeResult:
        history = await self._provision(ctx)
        try:
            args_json = await self._dispatch(ctx, extra_messages=history)
            report = self.parse(args_json)
        except StructuredOutputError:
            report = EnvReport(
                ready=False,
                install_steps=tuple(plan_commands(self._cwd)),
                notes="provisioner did not emit a structured report; seed steps recorded",
            )
        return NodeResult(output=report)

    # stage ① — the bash/read provisioning loop
    async def _provision(self, ctx: NodeContext) -> list[dict[str, Any]]:
        state = ctx.state
        seed = "\n".join(f"  {c}" for c in plan_commands(self._cwd)) or "  (no Python marker found)"
        request = state.request.raw_text if state.request is not None else ""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _PROVISION_SYSTEM.format(seed=seed)},
            {"role": "user", "content":
                f"{render_position(self.name, state)}\n\n"
                f"TASK CONTEXT (the fix to be validated later):\n{request}\n\n"
                "Set up the test environment now."},
        ]
        tool_ctx = ToolContext(
            turn_id="provision", cancel=ctx.cancel, cwd=self._cwd, ask=allow_all)
        for _ in range(MAX_ITERATIONS):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            text, calls = await self._stream_round(messages, ctx.sink)
            assistant: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                assistant["tool_calls"] = [
                    {"id": cid, "type": "function",
                     "function": {"name": name, "arguments": args or "{}"}}
                    for cid, name, args in calls]
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
                messages.append({"role": "tool", "tool_call_id": cid, "content": output})
        return messages[1:]  # hand provisioning history (minus its system prompt) to stage ②

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

    # stage ② — extraction
    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": _REPORT_SYSTEM},
            {"role": "user", "content": "Emit the EnvReport for the provisioning above."},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": "Emit what the env-prep learned: test command, steps, readiness.",
                "parameters": inline_refs(_EnvReportOut.model_json_schema()),
            },
        }

    def output_model(self) -> type[BaseModel]:
        return _EnvReportOut

    def parse(self, args_json: str) -> EnvReport:
        out = validate_output(_EnvReportOut, args_json, node=self.name)
        return EnvReport(
            ready=out.ready,
            test_command=out.test_command,
            install_steps=tuple(out.install_steps),
            notes=out.notes,
        )


def _safe_args(args_json: str) -> dict:
    try:
        v = json.loads(args_json or "{}")
        return v if isinstance(v, dict) else {"_": v}
    except (ValueError, TypeError):
        return {}
