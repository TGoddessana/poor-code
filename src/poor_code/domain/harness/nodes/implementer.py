"""implementer [A] — the only node that mutates the working tree. Runs a
read/write/edit/bash tool loop (mirrors ExploringNode's loop), then captures the
result as a ChangeRecord via the shadow-git snapshot (decision 2). Append vs
in-place refine follows decision 1: refine the latest attempt while it has no
run_result; start a fresh attempt after a real runner failure."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from poor_code.domain.harness.api_probe import focus_terms, probe_apis
from poor_code.domain.harness.ledger import render_build_ledger, task_section, render_acceptance
from poor_code.domain.harness.node import NodeContext, NodeResult, _LLMClientLike
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.harness.snapshot import GitSnapshot, default_git_dir
from poor_code.domain.harness.steering import driver_feedback_block, steering_block
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.session.models import (
    Attempt, ChangeRecord, GroundingStatus, Phase, SessionState)
from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)
from poor_code.provider.usage import tag

MAX_ITERATIONS = 50
# The most recent tool round is the basis for the model's NEXT decision, so it gets a
# bigger budget; older rounds are demoted to the standard clamp to keep re-sends bounded.
_LATEST_HEAD = 4000
_LATEST_TAIL = 4000
_NUDGE = (
    "You repeated the same tool call, or your last write/edit changed no file (no-op). "
    "Re-read the current state with the read tool and try a DIFFERENT fix. If VALIDATION "
    "already passes, stop calling tools."
)

_SYSTEM = (
    "You are the Implementer. Make the change described by the TASK using your tools: "
    "write/edit to change files, read/grep/glob/list to look first, bash to run commands. "
    "WHEN a RELEVANT CODE section is present, treat it as ground "
    "truth — edit against it, do not retype from memory. If it is absent or you need "
    "more than it shows, READ what you need with the read/grep tools before writing "
    "(bash is for running commands). Write ONLY inside EDITABLE PATHS.\n"
    "RULES:\n"
    "1. Stay strictly inside EDITABLE PATHS. Never touch anything outside them.\n"
    "2. Your goal is for the VALIDATION command to pass. NO stubs, NO skeletons, "
    "NO placeholders, NO 'fill in later' — write the real implementation that "
    "makes VALIDATION actually pass.\n"
    "3. Read ORIGINAL REQUEST, OVERALL GOAL, and your HARNESS POSITION so you know "
    "which slice of the whole you own.\n"
    "4. Keep calling tools until VALIDATION passes; once you confirm it passes, "
    "stop calling tools.\n"
    "4b. If STEPS are listed, execute them IN ORDER: apply the step's code to its "
    "file, then run its command and confirm the result matches EXPECTED before moving "
    "to the next step. If a step's command does not match EXPECTED, fix that step and "
    "re-run it before advancing — do not skip ahead.\n"
    "5. If PAST FAILURES or a REPAIR HINT are present, address them first.\n"
    "6. If the TASK runs a service (a server/daemon), launch it with bash background:true "
    "and LEAVE IT RUNNING — never kill it on success; it must outlive this run, and the "
    "validation probe checks the LIVE instance, so launch before the probe runs. If a "
    "launch fails (e.g. the port is already bound), READ the error and adapt — free the "
    "port, or use another port if the task allows — do not retry the identical launch."
)


class Implementer:
    name = "implementer"
    phase = Phase.IMPLEMENTING

    def __init__(self, llm: _LLMClientLike, cwd: Path, tools: ToolRegistry) -> None:
        self._llm = llm
        self._cwd = cwd
        self._tools = tools
        self._snapshot = GitSnapshot(git_dir=default_git_dir(cwd), work_tree=cwd)
        self._baselines: dict[str, str] = {}  # task_id → tree hash (per-run cache)
        # Real public APIs of the imported libraries, probed once and reused across the
        # many implementer attempts — so the model writes `TextArea.text`, not a recalled
        # `.value`. None = not yet probed; "" = probed, nothing groundable.
        self._api_digest: str | None = None

    async def run(self, ctx: NodeContext) -> NodeResult:
        state = ctx.state
        assert state.plan is not None and state.cursor is not None
        task = next((t for t in state.plan.tasks if t.id == state.cursor.task_id), None)
        assert task is not None, f"cursor task_id {state.cursor.task_id!r} not in plan"

        if self._api_digest is None:
            cc = state.understanding
            if cc is not None and cc.excerpts:
                req = state.requirement
                terms = focus_terms(
                    task.title, task.purpose,
                    *(req.summary, *req.acceptance) if req is not None else ())
                self._api_digest = await probe_apis(
                    cc.excerpts, terms, self._cwd, ctx.cancel)
            else:
                self._api_digest = ""

        await self._snapshot.init()
        if task.id not in self._baselines:
            self._baselines[task.id] = await self._snapshot.baseline()

        await self._loop(state, task, ctx)

        files, diff = await self._snapshot.diff_since(self._baselines[task.id])
        patch = ChangeRecord(files=files, diff=diff)

        latest = task.attempts[-1] if task.attempts else None
        if latest is not None and latest.run_result is None:
            attempt = Attempt(id=latest.id, patch=patch,
                              adversarial_rounds=latest.adversarial_rounds + 1)
        else:
            attempt = Attempt(id=f"{task.id}-a{len(task.attempts) + 1}",
                              patch=patch, adversarial_rounds=0)
        return NodeResult(output=attempt)

    async def _loop(self, state: SessionState, task, ctx: NodeContext) -> None:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": self._prompt(state, task)},
        ]
        tool_ctx = ToolContext(turn_id="implement", cancel=ctx.cancel,
                               cwd=self._cwd, ask=allow_all)
        full_output: dict[str, str] = {}          # cid -> full tool output (for re-clamping)
        tool_msg: dict[str, dict[str, Any]] = {}  # cid -> the tool message dict in `messages`
        prev_round: list[str] = []                # cids appended in the previous round
        last_tree = await self._snapshot.baseline()   # tree hash before this round
        prev_sig: tuple[tuple[str, str], ...] | None = None
        nudged_last = False
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
                return
            # A new round's results arrive → demote the previous round to the standard
            # clamp so only the freshest results carry the large budget.
            for cid in prev_round:
                tool_msg[cid]["content"] = clamp_tool_output(full_output[cid])
            round_cids: list[str] = []
            for cid, name, args in calls:
                if ctx.sink is not None:
                    ctx.sink.tool_started(cid, name, _safe_args(args))
                output = await self._run_tool(name, args, tool_ctx)
                if ctx.sink is not None:
                    if output.startswith("ERROR:"):
                        ctx.sink.tool_failed(cid, output)
                    else:
                        ctx.sink.tool_finished(cid, output)
                # The sink got the full output; the model gets a clamped copy. The latest
                # round keeps the large budget (the next decision reads it); the demote
                # loop above shrinks it once a newer round lands.
                msg: dict[str, Any] = {"role": "tool", "tool_call_id": cid,
                                       "content": clamp_tool_output(
                                           output, head=_LATEST_HEAD, tail=_LATEST_TAIL)}
                messages.append(msg)
                full_output[cid] = output
                tool_msg[cid] = msg
                round_cids.append(cid)
            prev_round = round_cids
            # B: repetition / no-op guard — nudge (never break) when the model spins.
            cur_tree = await self._snapshot.baseline()
            sig = tuple((name, args) for _, name, args in calls)  # raw-arg identity; reformatted repeats may slip, the tree branch backstops writes
            wrote = any(name in ("write", "edit") for _, name, _ in calls)
            stuck = sig == prev_sig or (wrote and cur_tree == last_tree)
            if stuck and not nudged_last:
                messages.append({"role": "user", "content": _NUDGE})
                nudged_last = True
            else:
                nudged_last = False
            prev_sig = sig
            last_tree = cur_tree

    async def _stream_round(self, messages, sink=None):
        text = ""
        pending: dict[str, dict[str, str]] = {}
        order: list[str] = []
        tag(self._llm, self.name)   # attribute this call's tokens to the implementer
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

    def _prompt(self, state: SessionState, task) -> str:
        scope = ", ".join(task.edit_scope.editable) or "(none)"
        refs = ""
        ctxt = task.context
        if ctxt is not None and ctxt.snippet:
            refs = ("\nRELEVANT CODE (ground truth — edit against THIS; do NOT retype "
                    "from memory):\n" + ctxt.snippet)
        elif ctxt is not None and ctxt.refs:
            refs = "\nRELEVANT CODE:\n" + "\n".join(
                f"  - {r.file}" + ("" if r.symbol is None else f"::{r.symbol}")
                for r in ctxt.refs)
        feedback = ""
        if state.feedback.entries:
            feedback = "\nPAST FAILURES TO AVOID:\n" + "\n".join(
                f"  - {e.failure_type}: {e.prevention_hint}" for e in state.feedback.entries)
        api = ""
        if self._api_digest:
            api = ("\nREAL APIs (use these exact attributes/methods; do NOT guess from "
                   f"memory):\n{self._api_digest}")
        # Unresolved questions + the explorer's "couldn't fully see this" note. Carried
        # forward so a gap the interviewer/explorer flagged drives a READ (via the read
        # tool) here instead of evaporating into a blind guess.
        unknowns = ""
        oq = state.requirement.open_questions if state.requirement is not None else ()
        cc = state.understanding
        notes = (cc.search_notes.strip()
                 if cc is not None and cc.grounding is GroundingStatus.NOT_FOUND else "")
        if oq or notes:
            parts = [f"  - open question: {q}" for q in oq]
            if notes:
                parts.append(f"  - exploration was incomplete: {notes}")
            unknowns = ("\nUNVERIFIED — confirm by READING the file (use the read/grep tools) "
                        "before coding against an assumption:\n" + "\n".join(parts))
        hint = f"\nREPAIR HINT: {state.repair_hint}" if state.repair_hint else ""
        env = ""
        if state.env_report is not None and (
                state.env_report.ready or state.env_report.test_command):
            er = state.env_report
            env = ("\nENVIRONMENT READY — the provisioner already set up the test env. "
                   "Dependencies are ALREADY installed: do NOT reinstall them and do NOT "
                   "hand-create stub/fake modules to satisfy imports. "
                   f"Run the project's tests with: {er.test_command or 'python -m pytest -q'}.")
            if er.notes:
                env += f" Notes: {er.notes}"
        hint = env + hint
        header = f"{render_position(self.name, state)}\n\n"
        if state.request is not None:
            header += f"ORIGINAL REQUEST:\n{state.request.raw_text}\n"
        if state.requirement is not None:
            header += f"OVERALL GOAL:\n{state.requirement.summary}\n"
        if state.understanding is not None and state.understanding.environment:
            header += ("ENVIRONMENT — write code ONLY for a runtime present below. Items "
                       "under 'NOT FOUND' are absent: do NOT use them and do NOT assume they "
                       "will be installed later (e.g. if node is NOT FOUND, do not write a "
                       "Node server — use an available runtime like python3). If a command "
                       "fails with 'not found', switch runtimes, do not retry it:\n"
                       f"{state.understanding.environment}\n")
        accept = render_acceptance(state)
        ledger = render_build_ledger(state)
        task_md = task_section(state.plan, task.id) if state.plan else task.title
        purpose = f"PURPOSE: {task.purpose}\n" if task.purpose else ""
        validation = (f"VALIDATION (make this pass): {task.how_to_validate}"
                      if task.how_to_validate else "")
        # Only the most-recent failed attempt's diff is re-shown; older attempts' lessons
        # are distilled into state.feedback. The latest is the most relevant to fix.
        prev = ""
        last = task.attempts[-1] if task.attempts else None
        if (last is not None and last.run_result is not None
                and not last.run_result.passed
                and last.patch is not None and last.patch.diff):
            prev = ("\nPREVIOUS ATTEMPT (failed validation — this exact patch did NOT pass; "
                    "fix what is wrong with it, do NOT resubmit it unchanged):\n"
                    + clamp_tool_output(last.patch.diff, head=2000, tail=2000))
        return (f"ACCEPTANCE SPEC (full target; your slice is THIS TASK below):\n{accept}\n\n"
                f"COMPLETED WORK (ledger):\n{ledger}\n\n"
                f"{header}"
                f"TASK: {task.title}\n{purpose}"
                f"DETAILS:\n{task_md}\nEDITABLE PATHS: {scope}\n"
                f"{validation}"
                f"{self._render_steps(task)}{refs}{api}{unknowns}{feedback}{prev}{hint}"
                f"{steering_block(state.steering_notes)}"
                f"{driver_feedback_block(state, self.name)}")

    @staticmethod
    def _render_steps(task) -> str:
        if not task.steps:
            return ""
        lines = ["\nSTEPS (apply in order; verify each against EXPECTED before the next):"]
        for s in task.steps:
            where = f"{s.file}" + (f" @ {s.anchor}" if s.anchor else "")
            lines.append(f"  [{s.id}] {s.kind.value} {where}")
            if s.body:
                lines.append(f"    code:\n{s.body}")
            if s.run:
                lines.append(f"    run: {s.run}    expected: {s.expected}")
        return "\n".join(lines)


def _safe_args(args_json: str) -> dict:
    try:
        v = json.loads(args_json or "{}")
        return v if isinstance(v, dict) else {"_": v}
    except (ValueError, TypeError):
        return {}
