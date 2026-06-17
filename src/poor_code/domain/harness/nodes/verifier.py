"""verifier — the observation-grounded adversarial Verifier (Plan: verification v2).

Replaces the deterministic bash-check chain (validator → validation_runner →
completion_gate) with a SINGLE intelligent node. There is NO model-authored bash
"acceptance command" run as an absolute floor anymore — that floor was measured to be
anti-correlated with ground truth (it abandoned correct work whose check crashed on its
own `set -o pipefail`, and blessed wrong work whose check was too weak).

Instead the Verifier is an agent with a bash + read/grep tool loop: it DRIVES the
implementation (runs it, starts servers and curls them, feeds boundary inputs, inspects
files/output), OBSERVES real behaviour, then judges adversarially against the CRITERIA
(natural-language definition of done). Its judgement IS the completion verdict — there is
no separate binding check to crash or to game.

Trust rests entirely on GROUNDING: the node must judge from what it OBSERVED, not from the
diff's appearance. Two stages mirror the Explorer: ① a tool loop to drive+observe, then
② a forced structured verdict over that observation history."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from poor_code.domain.harness.ledger import render_build_ledger, task_section
from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output)
from poor_code.domain.harness.nodes.execution import MAX_ATTEMPTS, _active
from poor_code.domain.harness.orientation import render_position
from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    Layer, Phase, Plan, Requirement, SessionState, TaskCompleted,
    Verdict, VerdictKind, effective_requirement)
from poor_code.domain.tool.registry import ToolRegistry

_TOOL_NAME = "judge"
MAX_ITERATIONS = 20


def _norm_criterion(s: str) -> str:
    """Normalize a criterion string for matching the oracle's binding set against the
    judge's echoed `checks[].criterion` — collapse case and surrounding/internal whitespace
    so a paraphrase in spacing/case still matches. NOT semantic matching; just transport
    robustness for the exact-text the judge is asked to echo."""
    return " ".join(s.split()).lower()

_OBSERVE_SYSTEM = (
    "You are the adversarial Verifier. The CRITERIA below define what 'done' means for "
    "this task. Your job in this phase: DRIVE the implementation and OBSERVE its REAL "
    "behaviour using your tools — run it, start any server in the BACKGROUND and curl it, "
    "and inspect the files and output it produced. Use bash to execute and "
    "read/grep/glob/list to inspect.\n"
    "Exercise the program the way each CRITERION says it is INVOKED — the actual command / "
    "file / endpoint — not an internal function you assume exists. If a criterion says "
    "'running `X` prints Y', run exactly `X` and read its REAL output; do not import a "
    "function and call it instead.\n"
    "NEVER DESTROY THE TASK'S INPUTS. The real input files are the artifact under test — and "
    "for a real user, their data. Do NOT overwrite, empty, truncate, replace, move, or "
    "corrupt any file the task provided or named, not even to probe an edge case. Mutating a "
    "named input in place poisons the result the real test grades and can delete a user's "
    "data. Leave the canonical inputs exactly as the implementer left them; the LAST run "
    "against THOSE inputs is what gets graded.\n"
    "To check an EDGE CASE the task implies (empty / boundary / malformed input, or an input "
    "the task never named, to expose a hard-coded impl), WRITE A SMALL THROWAWAY TEST IN "
    "$TMPDIR — use a bash heredoc to create your OWN scratch input and a short test script "
    "there, then either run the program against that scratch input (only when it accepts a "
    "path / stdin / arg) or import-and-exercise the logic from your scratch test, and assert "
    "the expected behaviour. STRONGLY prefer a written, re-runnable test in $TMPDIR over any "
    "one-off mutation of the real files. The observation you record is the scratch test's "
    "command and its real output.\n"
    "Be ADVERSARIAL: actively hunt for an input or case where it FAILS a criterion. Verify "
    "by OBSERVATION, never assume from how the code looks.\n"
    "REJECT FABRICATED OUTPUT. When the task extracts/recovers/transforms data, a result that "
    "is structurally valid (parses, non-empty) can still be INVENTED — placeholder or "
    "synthetic values the implementation made up instead of deriving from the real input "
    "(e.g. 'testword00..09', dummy rows). Trace the output back to the source: confirm the "
    "recovered items actually occur in / follow from the real input (grep them in the source "
    "bytes, compare counts). Do NOT mark such a criterion satisfied on structure alone.\n"
    "Do NOT modify the implementation's code (you only run, inspect, and write throwaway "
    "tests under $TMPDIR). When you have observed enough to judge every criterion, stop "
    "calling tools."
    " You may be given ORACLE-AUTHORED TESTS as evidence; running them is a strong signal, "
    "but a passing authored test is NOT sufficient on its own and a crashing one is NOT an "
    "automatic failure — your own adversarial observation is the verdict."
)

_JUDGE_SYSTEM = (
    "From what you OBSERVED above, judge this task against the CRITERIA. FIRST fill `checks` "
    "— one entry PER criterion, with: (a) `criterion`, (b) `observed` = the command you "
    "actually RAN and the real output you SAW for it, and (c) `satisfied` = whether that "
    "observation meets the criterion. A criterion you did NOT actually exercise has empty "
    "`observed` and is NOT satisfied — do not claim otherwise.\n"
    "THEN choose the verdict:\n"
    "- 'advance': ONLY when EVERY BINDING criterion has a real `observed` and is `satisfied`. "
    "Criteria listed under ADVISORY are ones the oracle abstained on — report what you see "
    "but they do not block advance. Default to repair_impl when any BINDING criterion is "
    "unobserved or unmet — do NOT rubber-stamp a result you did not verify by running it.\n"
    "- 'repair_impl': a criterion is unmet or unobserved. Cite it and the observed evidence; "
    "give a concrete fix hint.\n"
    "- 'repair_plan': the task/plan is mis-scoped (wrong files, wrong decomposition).\n"
    "Trust ONLY observation. Call judge once."
)


class _CriterionCheck(BaseModel):
    criterion: str
    observed: str = ""        # the command run + the real output seen ("" = not exercised)
    satisfied: bool = False


class _VerdictOut(BaseModel):
    checks: list[_CriterionCheck] = []
    verdict: Literal["advance", "repair_impl", "repair_plan"]
    hint: str = ""


class VerifierNode(AgentNode):
    name = "verifier"
    phase = Phase.IMPLEMENTING
    requires = (Plan, Requirement)
    produces = ()

    def __init__(self, llm: _LLMClientLike, cwd: Path, tools: ToolRegistry) -> None:
        super().__init__(llm)
        self._cwd = Path(cwd)
        self._tools = tools

    async def run(self, ctx: NodeContext) -> NodeResult:
        state = ctx.state
        task, attempt = _active(state)
        history = await self._observe(ctx, task)
        out = validate_output(
            _VerdictOut, await self._dispatch(ctx, extra_messages=history), node=self.name)
        raw_verdict, verdict, hint = out.verdict, out.verdict, out.hint

        # LENIENCY GUARD — the v2 false_accept frontier. A weak verifier observes (many bash
        # calls) but rubber-stamps 'advance'. Block an advance that is not backed by a real
        # per-criterion observation: every criterion must be marked satisfied AND carry the
        # output that was actually seen. Unbacked advance -> repair_impl.
        binding = self._binding_criteria(state)
        if verdict == "advance" and not self._observation_backed(out, binding):
            verdict, hint = "repair_impl", (hint or self._unbacked_hint(out, binding))

        # DIAGNOSTIC — persist the verdict + its grounding so a false_accept can be CLASSIFIED
        # post-hoc (weak criteria vs unobserved vs rubber-stamped vs fabricated evidence)
        # rather than inferred from pass/fail. Routed through the sink so it lands in the
        # POOR_CODE_DUMP_PROMPTS dump (headless/bench) and the TUI trace alike. No-op when off.
        self._emit_verdict_trace(ctx, history, out, raw_verdict, verdict, hint)

        if verdict == "advance":
            return self._done(task, attempt)
        if verdict == "repair_plan":
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.REPAIR, layer=Layer.PLAN,
                hint=hint or "Task is mis-scoped; re-plan."))
        # repair_impl — loosened authority: no rigid abandon. Repair up to the cap; at the
        # cap accept best-effort and move on rather than parking/abandoning correct-but-
        # unverified work. The cap counts the implementer's REFINEMENTS of the live attempt
        # (adversarial_rounds): with no validation_runner there is no run_result, so the
        # implementer refines the same attempt in place — len(attempts) stays 1 and cannot
        # be the cap (that bug looped implementer<->verifier forever).
        if attempt is None or attempt.adversarial_rounds >= MAX_ATTEMPTS:
            return self._done(task, attempt)
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=Layer.IMPLEMENTATION,
            hint=hint or "A criterion is not satisfied; fix the implementation."))

    @staticmethod
    def _binding_criteria(state: SessionState) -> set[str]:
        """Criteria the verdict gate must satisfy — everything the oracle did NOT mark
        'unknown', normalized for robust matching against the judge's echoed criterion text.
        Empty set means 'no acceptance spec' → fall back to requiring all checks."""
        if state.acceptance is None or not state.acceptance.checks:
            return set()
        return {_norm_criterion(c.criterion)
                for c in state.acceptance.checks if c.status != "unknown"}

    @staticmethod
    def _observation_backed(out: "_VerdictOut", binding: set[str]) -> bool:
        """'advance' is trustworthy only if every BINDING criterion was actually exercised:
        each has a satisfied check carrying observed output. Advisory ('unknown') criteria the
        oracle abstained on are excluded from the gate. With no acceptance spec (binding empty)
        — OR when the judge paraphrased every criterion so none string-match the binding set —
        fall back to requiring EVERY emitted check to be observed-and-satisfied (this avoids
        silently blocking a verified result, which would resurrect false_abandon)."""
        relevant = [c for c in out.checks if c.criterion and _norm_criterion(c.criterion) in binding]
        if not binding or not relevant:
            relevant = list(out.checks)
        return bool(relevant) and all(
            c.satisfied and c.observed.strip() for c in relevant)

    @staticmethod
    def _unbacked_hint(out: "_VerdictOut", binding: set[str]) -> str:
        relevant = [c for c in out.checks if c.criterion and _norm_criterion(c.criterion) in binding]
        if not binding or not relevant:
            relevant = list(out.checks)
        gaps = [c.criterion for c in relevant if not (c.satisfied and c.observed.strip())]
        detail = ("; ".join(gaps) if gaps
                  else "no per-criterion observations were provided")
        return ("Advance blocked: every binding criterion must be verified by running it and "
                f"observing the result. Not yet observed-and-satisfied: {detail}")

    def _emit_verdict_trace(self, ctx: NodeContext, history: list[dict[str, Any]],
                            out: "_VerdictOut", raw_verdict: str, final_verdict: str,
                            hint: str) -> None:
        """Append a 'verifier:verdict' record (observe transcript + per-criterion checks +
        raw/guarded verdict) to the sink. The whole verdict reasoning was previously dropped
        — only rendered transiently in the TUI — so a false_accept could not be classified
        from run artifacts. `raw_verdict` is what the model emitted; `final_verdict` is after
        the leniency guard, so a fired guard (raw=advance, final=repair_impl) is visible."""
        if ctx.sink is None or not hasattr(ctx.sink, "node_context"):
            return
        phase = ctx.state.cursor.phase.value if ctx.state.cursor else ""
        record = {
            "raw_verdict": raw_verdict,
            "final_verdict": final_verdict,
            "leniency_guard_fired": raw_verdict != final_verdict,
            "hint": hint,
            "checks": [c.model_dump() for c in out.checks],
        }
        messages = list(history) + [
            {"role": "verdict", "content": json.dumps(record, ensure_ascii=False, indent=2)}]
        ctx.sink.node_context(f"{self.name}:verdict", phase, messages)

    @staticmethod
    def _done(task, attempt) -> NodeResult:
        aid = attempt.id if attempt is not None else (
            task.attempts[-1].id if task.attempts else f"{task.id}-a1")
        return NodeResult(output=TaskCompleted(task_id=task.id, attempt_id=aid),
                          branch="done")

    # stage ① — drive + observe tool loop (mirrors ExploringNode._explore)
    async def _observe(self, ctx: NodeContext, task) -> list[dict[str, Any]]:
        state = ctx.state
        seed: list[dict[str, Any]] = [
            {"role": "system", "content": _OBSERVE_SYSTEM},
            {"role": "user", "content": self._observe_prompt(state, task)},
        ]
        if ctx.sink is not None and hasattr(ctx.sink, "node_context"):
            phase = state.cursor.phase.value if state.cursor else ""
            ctx.sink.node_context(self.name, phase, seed)
        return await self._tool_loop(
            ctx, seed_messages=seed, tools=self._tools, cwd=self._cwd,
            max_iterations=MAX_ITERATIONS, leak_text=False)

    def _observe_prompt(self, state: SessionState, task) -> str:
        criteria = self._criteria(state)
        attempt = task.attempts[-1] if task.attempts else None
        diff = "" if attempt is None or attempt.patch is None else attempt.patch.diff
        req = effective_requirement(state)
        header = f"{render_position(self.name, state)}\n\n"
        if state.request is not None:
            header += f"ORIGINAL REQUEST:\n{state.request.raw_text}\n"
        header += f"OVERALL GOAL:\n{req.summary}\n"
        task_md = task_section(state.plan, task.id) if state.plan else task.title
        authored = self._authored_tests(state)
        evidence = (
            f"\nORACLE-AUTHORED TESTS (strong EVIDENCE the oracle wrote and self-checked "
            f"BEFORE the implementation existed — you SHOULD run these as a starting point, "
            f"but they are NOT a binding floor; if one crashes, investigate rather than "
            f"abandon, and still observe adversarially):\n{authored}\n"
            if authored else "")
        return (
            f"CRITERIA (the definition of done — verify EACH by observation):\n{criteria}\n"
            f"{evidence}\n"
            f"{header}\n"
            f"TASK UNDER VERIFICATION:\n{task_md}\n\n"
            f"COMPLETED WORK (ledger):\n{render_build_ledger(state)}\n\n"
            f"PATCH JUST PRODUCED (do not trust it — observe its real effect):\n"
            f"{clamp_tool_output(diff, head=2000, tail=2000) if diff else '(empty)'}")

    @staticmethod
    def _criteria(state: SessionState) -> str:
        checks = state.acceptance.checks if state.acceptance else ()
        if checks:
            binding = [c for c in checks if c.status != "unknown"]
            advisory = [c for c in checks if c.status == "unknown"]
            lines = [f"  - {c.criterion}" for c in binding]
            if advisory:
                lines.append(
                    "\nADVISORY (the oracle could NOT establish the expected value and "
                    "ABSTAINED — observe if you can, REPORT what you see, but do NOT block "
                    "or bless on these; they are not part of the pass/fail gate):")
                lines += [f"  - {c.criterion}" for c in advisory]
            return "\n".join(lines)
        req = effective_requirement(state)
        return ("\n".join(f"  - {a}" for a in req.acceptance)
                or "  (no explicit criteria — judge against the REQUEST and the task PURPOSE)")

    @staticmethod
    def _authored_tests(state: SessionState) -> str:
        checks = state.acceptance.checks if state.acceptance else ()
        rows = [f"  - ({c.criterion}) -> {c.command}"
                for c in checks if c.command.strip()]
        return "\n".join(rows)

    # stage ② — verdict envelope
    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": "Emit your verdict for the task above, judging "
             "ONLY from what you observed."},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Judge the task against the criteria from observation.",
                             "parameters": inline_refs(_VerdictOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _VerdictOut

    def parse(self, args_json: str) -> _VerdictOut:
        return validate_output(_VerdictOut, args_json, node=self.name)


