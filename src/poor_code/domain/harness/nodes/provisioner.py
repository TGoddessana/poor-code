"""provisioner — agentic env-prep [A]. Runs ONCE after plan approval and before the
implementation layer. terminal-bench task containers ship only source (no pytest, no
deps, no built C-extensions); without provisioning every validation dies 'pytest not
found' / 'No module named ...' and the model gets zero feedback to refine a near-correct
fix — and (observed) wastes its budget hand-faking stub modules to satisfy imports.

This is a genuine AGENT, not a script: given the task, the cwd, and a strong prompt, the
model uses bash/read to PERCEIVE the project's real toolchain (pip / uv / poetry / make,
C-extensions, system packages) and INSTALL everything the downstream development needs,
then verifies the tests actually run. We do not hardcode the steps — the model decides.

The forward handoff (EnvReport → implementer) is derived DETERMINISTICALLY, not by a
second LLM 'emit' call. The earlier emit stage failed 0/4 on weak models because it was
force-fed thousands of lines of pip/apt logs as context. Instead we (a) capture the bash
commands the agent actually ran as `install_steps`, and (b) PROBE the test runner
(`pytest --co`) to set `ready` — measured truth, never a flaky model summary. The agent's
own closing summary becomes `notes`. Best effort by contract: it NEVER fails the run."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from poor_code.domain.harness.node import NodeContext, NodeResult, _LLMClientLike
from poor_code.domain.harness.nodes.execution import run_shell
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.harness.steering import driver_feedback_block, steering_block
from poor_code.domain.session.models import EnvReport, Phase, Request
from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.usage import tag
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)

MAX_ITERATIONS = 12
_TOOL_TAIL = 1600  # tool output fed BACK to the model is tailed: weak models drown in full pip logs
_TEST_COMMAND = "python -m pytest -q"
_PROBE = "python -m pytest --co -q"  # collection-only: imports resolve + runner is found
_PROBE_TIMEOUT = 300

# Deterministic seed for a standard Python project — offered to the agent in its prompt as
# a sensible default. The agent is free to ignore it and use the project's real toolchain.
_ENSURE_CC = (
    "command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 || "
    "(apt-get update -qq && apt-get install -y -qq --no-install-recommends "
    "gcc g++ python3-dev) || true"
)
_NUMPY = "python -m pip install -q numpy"  # present at BUILD time for C-extension projects
_EDITABLE_INSTALL = (
    "python -m pip install -q -e '.[test]' || "
    "python -m pip install -q -e '.[dev]' || "
    "python -m pip install -q -e ."
)


def _has_python_project(cwd: Path) -> bool:
    return (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists()


def plan_commands(cwd: Path) -> list[str]:
    """Deterministic seed bootstrap commands for a standard Python project rooted at
    `cwd`, used only to seed the agent's prompt. Empty when there is no Python marker."""
    if _has_python_project(cwd):
        return [_ENSURE_CC, _NUMPY, _EDITABLE_INSTALL]
    return []


_PROVISION_SYSTEM = (
    "You are the Provisioner — an agent whose ONE job is to make THIS project ready for "
    "all the development and testing work that follows on this task. The container ships "
    "only source: no dependencies, no test runner, no built C-extensions. You are setting "
    "up the ENVIRONMENT for everything downstream, not running a single fixed script.\n\n"
    "Work the problem with bash (and read):\n"
    "1. PERCEIVE — read the project's manifests to learn its REAL toolchain before acting: "
    "pyproject.toml, setup.py/.cfg, tox.ini, Makefile, README, requirements*.txt, and any "
    "lockfile (uv.lock, poetry.lock). Do not assume pip; use what the project actually uses "
    "(pip, uv, poetry, conda, make).\n"
    "2. INSTALL — install the project itself plus its test/build dependencies the project's "
    "documented way, and any SYSTEM packages needed to build native code (a C compiler and "
    "headers for numpy/scipy/astropy-style C-extensions). If the project uses uv, prefer "
    "`uv sync` / `uv pip install`; otherwise `python -m pip install -e '.[test]'`.\n"
    "3. VERIFY — actually run the test runner and read the output (e.g. `python -m pytest "
    "--co -q` to collect, or run one test). Keep going until imports resolve and the runner "
    "is found.\n\n"
    "CONSTRAINTS: Set up the environment ONLY — never edit source, never write the fix, and "
    "NEVER hand-create stub or fake modules to satisfy an import (install the real thing). "
    "When the test runner actually runs, briefly summarize what you did and stop.\n\n"
    "A reasonable default sequence for a standard Python project (adapt as needed):\n{seed}\n"
)


class Provisioner:
    name = "provisioner"
    phase = Phase.PLANNING
    requires = (Request,)
    produces = (EnvReport,)

    def __init__(self, llm: _LLMClientLike, cwd: Path, tools: ToolRegistry) -> None:
        self._llm = llm
        self._cwd = cwd
        self._tools = tools

    async def run(self, ctx: NodeContext) -> NodeResult:
        commands, summary = await self._provision(ctx)
        report = await self._build_report(ctx, commands, summary)
        return NodeResult(output=report)

    # --- the agentic perceive-and-install loop -------------------------------------
    async def _provision(self, ctx: NodeContext) -> tuple[list[str], str]:
        """Drive the model's bash/read loop. Returns (executed bash commands, final
        free-text summary). Tool outputs are tailed before being fed back so a weak
        model is not drowned by full pip/apt logs."""
        state = ctx.state
        seed = "\n".join(f"  {c}" for c in plan_commands(self._cwd)) or "  (no Python marker found)"
        request = state.request.raw_text if state.request is not None else ""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _PROVISION_SYSTEM.format(seed=seed)},
            {"role": "user", "content":
                f"{render_position(self.name, state)}\n\n"
                f"TASK CONTEXT (the fix to be validated later):\n{request}\n\n"
                "Set up the environment now."
                f"{steering_block(state.steering_notes)}"
                f"{driver_feedback_block(state, self.name)}"},
        ]
        tool_ctx = ToolContext(
            turn_id="provision", cancel=ctx.cancel, cwd=self._cwd, ask=allow_all)
        executed: list[str] = []
        summary = ""
        for _ in range(MAX_ITERATIONS):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            text, calls = await self._stream_round(messages, ctx.sink)
            if text.strip():
                summary = text.strip()
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
                if name == "bash":
                    cmd = _extract_command(args)
                    if cmd:
                        executed.append(cmd)
                if ctx.sink is not None:
                    ctx.sink.tool_started(cid, name, _safe_args(args))
                output = await self._run_tool(name, args, tool_ctx)
                if ctx.sink is not None:
                    if output.startswith("ERROR:"):
                        ctx.sink.tool_failed(cid, output)
                    else:
                        ctx.sink.tool_finished(cid, output)
                messages.append({"role": "tool", "tool_call_id": cid,
                                 "content": _tail(output)})
        return executed, summary

    async def _stream_round(self, messages: list[dict[str, Any]], sink: object | None = None):
        text = ""
        pending: dict[str, dict[str, str]] = {}
        order: list[str] = []
        tag(self._llm, self.name)   # attribute this call's tokens to the provisioner
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

    # --- deterministic EnvReport derivation ----------------------------------------
    async def _build_report(
        self, ctx: NodeContext, commands: list[str], summary: str
    ) -> EnvReport:
        """Derive the report from MEASURED state, not a model emit. Skip the probe when
        nothing was provisioned and there is no Python project (cheap no-op upstream)."""
        if not commands and not _has_python_project(self._cwd):
            return EnvReport(ready=False, install_steps=(),
                             notes=summary or "no python project detected; nothing provisioned")
        ready, probe_note = await self._probe(ctx)
        notes = " | ".join(n for n in (summary, probe_note) if n)
        return EnvReport(
            ready=ready,
            test_command=_TEST_COMMAND,
            install_steps=tuple(commands),
            notes=notes[:600],
        )

    async def _probe(self, ctx: NodeContext) -> tuple[bool, str]:
        """Measured readiness: can pytest COLLECT the suite? (imports resolve, runner found)"""
        code, out = await run_shell(_PROBE, self._cwd, ctx.cancel, timeout=_PROBE_TIMEOUT)
        if code == 0:
            return True, "pytest collection ok"
        return False, f"pytest collection failed (exit {code}): {out[-200:].strip()}"


def _extract_command(args_json: str) -> str:
    try:
        v = json.loads(args_json or "{}")
        return v.get("command", "") if isinstance(v, dict) else ""
    except (ValueError, TypeError):
        return ""


def _tail(output: str) -> str:
    if len(output) <= _TOOL_TAIL:
        return output
    return "...[earlier output truncated]...\n" + output[-_TOOL_TAIL:]


def _safe_args(args_json: str) -> dict:
    try:
        v = json.loads(args_json or "{}")
        return v if isinstance(v, dict) else {"_": v}
    except (ValueError, TypeError):
        return {}
