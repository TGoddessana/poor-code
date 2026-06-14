"""acceptance_oracle — designs the GLOBAL, plan-independent acceptance check (the
authoritative 'done'). Reads only the binding Requirement (+ CodeContext as
reference); never the plan. Emits a runnable AcceptanceSpec via one tool call."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from poor_code.domain.harness.api_probe import focus_terms, probe_apis
from poor_code.domain.harness.node import (
    AgentNode, NodeContext, NodeResult, _LLMClientLike, validate_output)
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, GroundingStatus, Phase, SessionState,
    effective_requirement,
)

_MAX_EXCERPT_IN_PROMPT = 1800   # per-file body slice handed to the oracle as ground truth

_TOOL_NAME = "emit_acceptance"

_AUTHOR_SYSTEM = (
    "You are the Acceptance Oracle, in the AUTHORING phase. Before you state the criteria, "
    "you will WORK OUT the correct expected behaviour for this task using your tools — do "
    "NOT recall expected values from memory; COMPUTE/DERIVE them from the real input data. A "
    "model that recalls a number guesses; a model that runs a script gets it right.\n"
    "For each criterion that pins a concrete expected value or output: read the actual input "
    "(read/grep/glob/list), then WRITE A SMALL TEST OR REFERENCE COMPUTATION IN $TMPDIR (bash "
    "heredoc) and RUN it to derive the expected result deterministically.\n"
    "DISCRIMINATION SELF-CHECK — a test that passes everything is useless. Confirm each test "
    "you author (a) runs cleanly and (b) actually FAILS on an obviously wrong / stub / empty "
    "implementation. If it cannot be made to fail on a wrong stub, it is too weak.\n"
    "HONEST ABSTENTION — if after using your tools you still cannot establish the expected "
    "behaviour with confidence (the computation is unstable, the logic is a trap you are not "
    "sure you got right, or you cannot read the source fully), mark that criterion 'unknown' "
    "rather than guessing an expected value. A guessed expectation is the bug we are removing.\n"
    "NEVER DESTROY THE TASK'S INPUTS — do NOT overwrite, empty, truncate, replace, move, or "
    "corrupt any file the task provided or named. Do ALL scratch work in $TMPDIR; the canonical "
    "inputs must survive unchanged (they are the artifact the real test grades, and a user's "
    "data). The implementation does NOT exist yet — never try to run a candidate 'solution'; "
    "derive the expectation independently from inputs + the requirement.\n"
    "Record, for each criterion, the exact commands you ran and the real output you saw — that "
    "becomes your `evidence` and backs your `confidence`. When you have worked out every "
    "criterion you can, stop calling tools."
)

_SYSTEM = (
    "You are the Acceptance Oracle, in the EMIT phase. Using the EXPECTED BEHAVIOUR you just "
    "worked out with your tools above, define the GLOBAL CRITERIA for 'done' — what an "
    "observer must SEE to be sure the result is correct. A separate observe-judge Verifier "
    "will DRIVE the program and OBSERVE its real behaviour to check each criterion; the test "
    "you AUTHORED is handed to it as strong EVIDENCE (it MAY run it) but is NOT a binding "
    "gate — the criterion TEXT is authoritative. State each criterion clearly, concretely, "
    "and adversarially so a wrong implementation cannot pass it. One precise criterion per "
    "acceptance point.\n"
    "For each criterion set: `command` = the executable test you authored and self-checked in "
    "the authoring phase (\"\" if none); `status` = 'verified' when you established the "
    "expected behaviour with confidence, else 'unknown' (honest abstention — do NOT emit a "
    "guessed expected value as 'verified'); `confidence` = high/medium/low; `evidence` = the "
    "commands you ran and the real output you saw that backs this.\n"
    "RULES:\n"
    "1. COVER THE WHOLE CONTRACT — test the PROGRAM the way the task will actually run it, "
    "not an internal function you imagine. Read the REQUIREMENT for exactly HOW it is "
    "invoked (the command / CLI / script name / file path / port / endpoint it names) and "
    "the FORM of the result (stdout text, a named file's content, an HTTP response, an exit "
    "code). Your criteria must exercise THAT external behaviour — e.g. 'running "
    "`python grid_transform.py < in.txt` prints exactly <...>' or 'GET /health returns 200 "
    "with body OK' — and NEVER an assumed API (do not invent a `solve()` function the task "
    "did not specify). If the requirement names a script/command/file/port, criteria MUST "
    "use it; make the required INPUT/OUTPUT FORMAT itself a criterion.\n"
    "2. State the EXACT expected value, not a vague goal — 'the output is the 6x6 grid "
    "<...>', not 'transforms correctly'. Check behaviour an observer sees by RUNNING it "
    "(file content, response, exit status), not that some string appears somewhere.\n"
    "ANTI-GAMING (a weak criterion lets a wrong or hard-coded impl pass):\n"
    "3. Demand EXACT equality of the whole value, never a substring that would also match a "
    "wrong value (e.g. a criterion satisfied by 5 must not be satisfied by 55).\n"
    "4. Name AT LEAST ONE input the requirement never mentions, with its correct expected "
    "output, so a lookup-table / hard-coded implementation fails.\n"
    "5. Name AT LEAST ONE boundary / extreme input (empty, zero, negative, very large, or "
    "malformed) and the behaviour expected for it.\n"
    "6. GROUND any API you reference against the CODE CONTEXT 'REAL APIs' below — name the "
    "real attribute/method (e.g. `.text`, not a recalled `.value`).\n"
    "7. NON-DESTRUCTIVE — the alternate / boundary inputs in rules 4-5 must be checkable "
    "WITHOUT altering a named task input file. The task's real input files are the artifact "
    "under test (and, for a real user, their data); they must SURVIVE verification unchanged. "
    "So do NOT phrase a criterion as 'when <a named input file> is replaced / emptied / "
    "truncated / corrupted' — that forces the Verifier to DESTROY the very thing being "
    "graded. Instead, when the program accepts input through a real channel (a CLI arg, "
    "stdin, or a path it takes as a parameter), name the alternate / boundary input THERE; "
    "if it only reads a FIXED hard-coded path, drop the input-swap probe and instead demand "
    "EXACT equality of the canonical output (rule 3) — anti-gaming, but non-destructive.\n"
    "8. NO FABRICATION — when the task EXTRACTS, RECOVERS, or COPIES data from a source, the "
    "result must be DERIVED from that real source, never invented. If you cannot state the "
    "exact expected output (you cannot fully read the source yourself), do NOT settle for "
    "STRUCTURE-ONLY criteria (valid JSON / a non-empty list / count > 0) — those are passed "
    "by a fabricated or placeholder result (e.g. synthetic 'testword00..09', 'foo', dummy "
    "rows). Add a TRACEABILITY criterion: each recovered/extracted item must be verifiably "
    "present in the real source (e.g. the recovered strings actually occur in the source "
    "file's bytes / rows). This applies to EXTRACTION, not COMPUTATION — for a computed/"
    "derived value (a sum, average, count, transform), the output legitimately differs from "
    "the input, so pin its EXACT value instead (rule 2), do not demand it appear in the "
    "source.\n"
    "Emit one criterion per acceptance point. A criterion whose expected value you could not "
    "establish MUST be 'unknown', never a guess dressed up as 'verified'. Call emit_acceptance "
    "once."
)


class _AcceptanceCheckOut(BaseModel):
    criterion: str
    command: str = ""        # the executable test the oracle AUTHORED (evidence, not a floor)
    rationale: str = ""
    status: str = "verified" # "verified" | "unknown" (honest abstention)
    confidence: str = ""     # "high" | "medium" | "low"
    evidence: str = ""       # what the oracle observed while authoring/self-testing


class _AcceptanceSpecOut(BaseModel):
    checks: list[_AcceptanceCheckOut] = []


class AcceptanceOracle(AgentNode):
    name = "acceptance_oracle"
    phase = Phase.PLANNING

    def __init__(self, llm: _LLMClientLike, cwd: Path = Path(".")) -> None:
        super().__init__(llm)
        self._cwd = cwd
        # Real public APIs of the libraries the explored code imports — probed in run()
        # so build_messages (sync) can hand the oracle ground truth instead of leaving
        # it to RECALL `TextArea.text` vs `.value` from training. "" when nothing to probe.
        self._api_digest = ""

    async def run(self, ctx: NodeContext) -> NodeResult:
        cc = ctx.state.understanding
        if cc is not None and cc.excerpts:
            req = effective_requirement(ctx.state)
            terms = focus_terms(req.summary, *req.acceptance, *req.assumptions)
            self._api_digest = await probe_apis(cc.excerpts, terms, self._cwd, ctx.cancel)
        args_json = await self._dispatch(ctx)
        return NodeResult(output=self.parse(args_json))

    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        req = effective_requirement(state)
        prior = ""
        if state.repair_hint:
            prior = (
                "PRIOR REJECTION — the adversarial critic BROKE your previous acceptance "
                "design with the COUNTEREXAMPLE below (a wrong implementation that still "
                "passed, or a correct one that failed). Your redesigned checks MUST make "
                "this counterexample FAIL; do NOT resubmit checks it would still pass. "
                "Address the specific hole it exposes (e.g. switch substring matches to "
                "exact equality, add an input the examples never cover).\n"
                f"<<< COUNTEREXAMPLE\n{state.repair_hint}\n>>>\n\n")
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"{prior}"
                "REQUIREMENT:\n"
                f"summary: {req.summary}\n"
                f"acceptance:\n{self._bullets(req.acceptance)}\n"
                f"out_of_scope:\n{self._bullets(req.out_of_scope)}\n"
                f"assumptions:\n{self._bullets(req.assumptions)}\n"
                f"open_questions (unresolved — do NOT design a check that pretends these are "
                f"settled):\n{self._bullets(req.open_questions)}\n\n"
                f"CODE CONTEXT:\n{self._context_digest(state)}")},
        ]

    def output_tool(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": _TOOL_NAME,
                             "description": "Emit the global acceptance checks.",
                             "parameters": inline_refs(_AcceptanceSpecOut.model_json_schema())}}

    def output_model(self) -> type[BaseModel]:
        return _AcceptanceSpecOut

    def parse(self, args_json: str) -> AcceptanceSpec:
        out = validate_output(_AcceptanceSpecOut, args_json, node=self.name)
        return AcceptanceSpec(checks=tuple(
            AcceptanceCheck(
                criterion=c.criterion, command=c.command, rationale=c.rationale,
                status=(c.status or "verified"), confidence=c.confidence,
                evidence=c.evidence)
            for c in out.checks))

    @staticmethod
    def _bullets(items: tuple[str, ...]) -> str:
        if not items:
            return "  (none)"
        return "\n".join(f"  - {item}" for item in items)

    def _context_digest(self, state: SessionState) -> str:
        cc = state.understanding
        if cc is None:
            return "(none)"
        lines: list[str] = []
        if cc.grounding is GroundingStatus.GREENFIELD:
            lines.append("MODE: greenfield (create-from-scratch; no existing code to ground).")
        if cc.summary:
            lines.append(f"summary: {cc.summary}")
        # The explorer's self-diagnosis when it could NOT fully locate the code (truncated
        # bodies, unseen handlers). Surfaced so the oracle does not design a check that
        # asserts behaviour nobody actually confirmed exists.
        if cc.grounding is GroundingStatus.NOT_FOUND and cc.search_notes.strip():
            lines.append(f"INCOMPLETE EXPLORATION (unverified — treat with caution): "
                         f"{cc.search_notes.strip()}")
        if cc.candidates:
            refs = ", ".join(
                f"{r.file}:{r.symbol}" if r.symbol else r.file for r in cc.candidates)
            lines.append(f"relevant code: {refs}")
        # Real API ground truth (probed in run()) — so checks assert against attributes the
        # objects actually have, not ones the model recalled. This is the single most direct
        # defence against the unwinnable-check bug (`.value` on a type whose attr is `.text`).
        if self._api_digest:
            lines.append(f"REAL APIs (use these exact attributes, do NOT guess):\n{self._api_digest}")
        # Verbatim source the explorer read — ground truth, not a model-retyped paraphrase.
        for ex in cc.excerpts:
            body = ex.text[:_MAX_EXCERPT_IN_PROMPT]
            trunc = " …(truncated)" if (ex.truncated or len(ex.text) > _MAX_EXCERPT_IN_PROMPT) else ""
            lines.append(f"--- {ex.path}{trunc} ---\n{body}")
        return "\n".join(lines) if lines else "(none)"
