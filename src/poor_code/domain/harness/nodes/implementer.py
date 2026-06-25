"""implementer [A] — the only node that mutates the working tree. Runs a
read/write/edit/bash tool loop (mirrors ExploringNode's loop), then captures the
result as a ChangeRecord via the shadow-git snapshot (decision 2). Append vs
in-place refine follows decision 1: refine the latest attempt while it has no
run_result; start a fresh attempt after a real runner failure."""
from __future__ import annotations

from pathlib import Path

from poor_code.domain.harness.api_probe import focus_terms, probe_apis
from poor_code.domain.harness.nodes.execution import MAX_ATTEMPTS, _active
from poor_code.domain.harness.ledger import render_build_ledger, task_section, render_acceptance
from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, SideEffectCompletion, _DefaultHooks, _LoopRound, _LLMClientLike)
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.harness.snapshot import GitSnapshot, default_git_dir
from poor_code.domain.harness.steering import driver_feedback_block, steering_block
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.session.models import (
    Attempt, ChangeRecord, CodeContext, GroundingStatus, Phase, Plan, Requirement,
    SessionState)
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.bash import BashTool, BashParams
from poor_code.domain.tool.base import ToolContext, allow_all

MAX_ITERATIONS = 50
GATE_TIMEOUT = 120          # seconds for a deterministic RED/GREEN gate command
STEP_MAX_ITERATIONS = 15    # bounded sub-loop budget while authoring ONE step
STEP_REPAIR_CAP = 3         # re-author attempts per step before skip/escalate
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
    "4b. If STEPS are listed, execute them IN ORDER. For a 'test' step, write the test "
    "and RUN it and CONFIRM it FAILS before you write the matching 'impl' step (a test "
    "that passes before the code exists is testing nothing). For each step, apply its code "
    "to its file, then run its command and confirm the result matches EXPECTED before "
    "moving to the next; if it does not match, fix that step and re-run it before advancing "
    "— do not skip ahead.\n"
    "5. If PAST FAILURES or a REPAIR HINT are present, address them first.\n"
    "6. If the TASK runs a service (a server/daemon), launch it with bash background:true "
    "and LEAVE IT RUNNING — never kill it on success; it must outlive this run, and the "
    "validation probe checks the LIVE instance, so launch before the probe runs. If a "
    "launch fails (e.g. the port is already bound), READ the error and adapt — free the "
    "port, or use another port if the task allows — do not retry the identical launch."
)

_STEP_SYSTEM = (
    "You are the Implementer, working ONE step of a test-driven plan. Write ONLY the "
    "code for THIS step using write/edit; read/grep to look first. Stay strictly inside "
    "EDITABLE PATHS. The planner's DRAFT for this step is a guide — adapt it to the REAL "
    "current file contents; do not retype blindly. When the step's code is written, stop "
    "calling tools."
)


class _ImplementerHooks(_DefaultHooks):
    """Implementer-only per-round behavior: the LATEST round's tool outputs keep a big
    budget while prior rounds are demoted to the standard clamp; and a no-op/repetition
    nudge fires (once, non-consecutively) when the model repeats a call or a write changes
    no file. Holds the cross-round state the old _loop kept in locals."""
    def __init__(self, snapshot: GitSnapshot):
        self._snapshot = snapshot
        self._prev: _LoopRound | None = None
        self._last_tree: str = ""
        self._prev_sig: tuple[tuple[str, str], ...] | None = None
        self._nudged_last = False

    def clamp(self, output: str) -> str:
        return clamp_tool_output(output, head=_LATEST_HEAD, tail=_LATEST_TAIL)

    async def before_loop(self) -> None:
        self._last_tree = await self._snapshot.baseline()

    async def after_round(self, rnd: _LoopRound) -> None:
        if self._prev is not None:
            for cid, msg in self._prev.tool_msgs.items():
                msg["content"] = clamp_tool_output(self._prev.full_output[cid])
        self._prev = rnd
        cur_tree = await self._snapshot.baseline()
        sig = tuple((name, args) for _, name, args in rnd.calls)
        wrote = any(name in ("write", "edit") for _, name, _ in rnd.calls)
        stuck = sig == self._prev_sig or (wrote and cur_tree == self._last_tree)
        if stuck and not self._nudged_last:
            rnd.messages.append({"role": "user", "content": _NUDGE})
            self._nudged_last = True
        else:
            self._nudged_last = False
        self._prev_sig = sig
        self._last_tree = cur_tree


class Implementer(AgentNode):
    name = "implementer"
    phase = Phase.IMPLEMENTING
    requires = (Plan, Requirement, CodeContext)
    produces = ()

    def __init__(self, llm: _LLMClientLike, cwd: Path, tools: ToolRegistry) -> None:
        super().__init__(llm)
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
        state.require(Plan)
        assert state.cursor is not None
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

        completion = SideEffectCompletion(extract=self._extract_attempt(task))
        return await completion.extract_async(ctx)

    def _extract_attempt(self, task):
        async def _extract(ctx):
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
        return _extract

    async def _loop(self, state: SessionState, task, ctx: NodeContext) -> None:
        seed = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": self._prompt(state, task)},
        ]
        # Diagnostic hook: surface the implementer's initial prompt through the same
        # node_context sink AgentNodes use (so a prompt dump sees the seed).
        if ctx.sink is not None and hasattr(ctx.sink, "node_context"):
            phase = state.cursor.phase.value if state.cursor else ""
            ctx.sink.node_context(self.name, phase, seed)
        await self._tool_loop(
            ctx, seed_messages=seed, tools=self._tools, cwd=self._cwd,
            max_iterations=MAX_ITERATIONS, leak_text=False,
            hooks=_ImplementerHooks(self._snapshot))

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

    @staticmethod
    def _gate_command(step, task) -> str:
        """The command whose exit code decides RED/GREEN for this step: the step's own
        `run` if it set one, else the task's outer `how_to_validate`."""
        return step.run.strip() or task.how_to_validate.strip()

    async def _run_gate(self, command: str, ctx: NodeContext) -> int:
        """Run a gate command in the work tree and return its exit code. Empty command →
        0 (non-blocking pass: nothing to gate on). Reuses BashTool for the project's
        process-group timeout/kill handling."""
        if not command.strip():
            return 0
        tctx = ToolContext(turn_id=self.name, cancel=ctx.cancel,
                           cwd=self._cwd, ask=allow_all)
        res = await BashTool().execute(
            BashParams(command=command, timeout=GATE_TIMEOUT), tctx)
        return int(res.metadata.get("exit_code", 1))

    def _step_seed(self, state, task, step, feedback: str) -> list[dict]:
        scope = ", ".join(task.edit_scope.editable) or "(none)"
        if step.kind.value == "test":
            role = ("Write the TEST for this step. It must assert the behavior that does "
                    "NOT exist yet, so it FAILS now. DO NOT write the implementation.")
        else:
            role = ("Write the IMPLEMENTATION for this step to MAKE THE TEST PASS.")
        draft = f"\nPLANNER DRAFT (adapt to real files):\n{step.body}" if step.body else ""
        fb = f"\nPREVIOUS GATE RESULT (fix this):\n{feedback}" if feedback else ""
        user = (f"OVERALL TASK: {task.title} — {task.purpose}\n"
                f"STEP [{step.id}] kind={step.kind.value} file={step.file}\n"
                f"{role}\nEDITABLE PATHS: {scope}{draft}{fb}")
        return [{"role": "system", "content": _STEP_SYSTEM},
                {"role": "user", "content": user}]

    async def _author_step(self, state, task, step, ctx: NodeContext,
                           feedback: str = "") -> None:
        seed = self._step_seed(state, task, step, feedback)
        if ctx.sink is not None and hasattr(ctx.sink, "node_context"):
            phase = state.cursor.phase.value if state.cursor else ""
            ctx.sink.node_context(self.name, phase, seed)
        await self._tool_loop(
            ctx, seed_messages=seed, tools=self._tools, cwd=self._cwd,
            max_iterations=STEP_MAX_ITERATIONS, leak_text=False,
            hooks=_ImplementerHooks(self._snapshot))

    async def _drive_test_step(self, state, task, step, ctx: NodeContext) -> str:
        """Author the test, then require the gate to FAIL (RED). A passing gate means the
        test asserts nothing new (vacuous) — re-author with that feedback up to the cap,
        then SKIP the test rather than abandon otherwise-correct work."""
        cmd = self._gate_command(step, task)
        feedback = ""
        for _ in range(STEP_REPAIR_CAP):
            await self._author_step(state, task, step, ctx, feedback)
            if await self._run_gate(cmd, ctx) != 0:
                return "red"
            feedback = ("Your test PASSED before any implementation exists, so it asserts "
                        "nothing new. Rewrite it to assert the behavior that does not exist "
                        "yet, so it FAILS now.")
        return "skipped"

    async def _drive_impl_step(self, state, task, step, ctx: NodeContext) -> str:
        """Author the implementation, then require the gate to PASS (GREEN). On repeated
        failure: escalate to repair_plan (the plan/scope is suspect) UNLESS the outer
        repair cap is reached, in which case proceed best-effort so we never loop the
        planner forever or false-abandon correct-but-unverified work (spec §6)."""
        cmd = self._gate_command(step, task)
        feedback = ""
        for _ in range(STEP_REPAIR_CAP):
            await self._author_step(state, task, step, ctx, feedback)
            if await self._run_gate(cmd, ctx) == 0:
                return "green"
            feedback = (f"The implementation did NOT make the gate pass.\n"
                        f"Gate command: {cmd}\nFix the implementation so it passes.")
        _, attempt = _active(state)
        if attempt is not None and attempt.adversarial_rounds >= MAX_ATTEMPTS:
            return "best_effort"
        return "escalate"
