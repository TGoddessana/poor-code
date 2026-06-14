import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.acceptance_oracle import AcceptanceOracle
from poor_code.domain.session.models import (
    AcceptanceSpec, CodeContext, CodeRef, FileExcerpt, GroundingStatus, Request,
    RequestKind, Requirement, SessionState,
)
from poor_code.domain.harness import api_probe as _api_probe_mod
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.seen_messages = None

    async def stream(self, messages, tools, response_format=None):
        self.seen_messages = messages
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=json.dumps(self.payload))
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _state(repair_hint=None):
    return SessionState(
        requirement=Requirement(
            summary="create hello.txt containing 'Hello, world!\\n'",
            acceptance=("hello.txt has exact content",),
        ),
        understanding=CodeContext(grounding=GroundingStatus.GREENFIELD),
        repair_hint=repair_hint,
    )


@pytest.mark.asyncio
async def test_oracle_emits_acceptance_spec():
    llm = FakeLLM({"checks": [
        {"criterion": "exact content", "command": "printf 'Hello, world!\\n' | diff - hello.txt",
         "rationale": "content equality, no derived metric"}]})
    res = await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    assert isinstance(res.output, AcceptanceSpec)
    assert res.output.checks[0].criterion == "exact content"
    assert "diff - hello.txt" in res.output.checks[0].command


@pytest.mark.asyncio
async def test_oracle_falls_back_to_request_when_requirement_absent():
    # Headless (FULL_AUTO) skips the interviewer, so state.requirement is None. The
    # oracle must ground its global done-check on the raw request (the issue text,
    # which carries the reproduction) instead of asserting — this is what makes the
    # check independent of the planner's self-authored per-task validations.
    issue = ("ascii.qdp assumes upper-case commands. "
             "Table.read of 'read serr 1 2' should not crash.")
    state = SessionState(
        requirement=None,
        request=Request(raw_text=issue, kind=RequestKind.ENGINEERING),
        understanding=CodeContext(grounding=GroundingStatus.GREENFIELD),
    )
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "read serr 1 2" in prompt  # the issue's reproduction reached the oracle


@pytest.mark.asyncio
async def test_oracle_prompt_includes_requirement_and_grounding_rules():
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    system = llm.seen_messages[0]["content"]
    assert "create hello.txt" in prompt
    assert "hello.txt has exact content" in prompt
    # v2: criteria-based — observable content + exact equality (no bash `diff` authoring)
    assert "content" in system.lower() and "exact" in system.lower()


@pytest.mark.asyncio
async def test_oracle_system_states_task_independent_anti_gaming_rules():
    # These are the three universal anti-gaming invariants (NOT task-specific):
    # exact-equality over substring, at least one non-example input (lookup-table
    # defence), and at least one boundary/extreme input.
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    system = llm.seen_messages[0]["content"].lower()
    assert "substring" in system          # exact-equality, not substring match
    assert "lookup" in system             # defend against lookup-table / hard-coded outputs
    assert "boundary" in system           # exercise extreme / edge inputs


@pytest.mark.asyncio
async def test_oracle_system_forbids_destructive_input_probes():
    # E-poisoning fix: rules 4-5 (alternate / boundary inputs) must be NON-DESTRUCTIVE —
    # the oracle must NOT emit criteria that require replacing/emptying/corrupting a named
    # task input (which forces the Verifier to destroy the artifact under test / a user's
    # data). The anti-gaming words (boundary/lookup/substring) must SURVIVE this addition.
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    system = llm.seen_messages[0]["content"].lower()
    assert "non-destructive" in system
    assert "replaced" in system and ("survive" in system or "unchanged" in system)
    # anti-gaming intent preserved
    assert "boundary" in system and "lookup" in system and "substring" in system


@pytest.mark.asyncio
async def test_oracle_system_demands_traceability_for_extraction_not_computation():
    # sqlite frontier: when the answer can't be precomputed (recovery/extraction), structure-
    # only criteria (valid JSON / count>0) pass FABRICATED placeholder output. The oracle must
    # demand traceability to the real source — and must NOT impose that on COMPUTED outputs
    # (a sum/average legitimately is not present in the source).
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    system = llm.seen_messages[0]["content"].lower()
    assert "fabricat" in system
    assert "traceab" in system or "occur in the real source" in system or "present in the real source" in system
    assert "computation" in system or "computed" in system   # carve-out so averages aren't rejected


@pytest.mark.asyncio
async def test_oracle_prompt_carries_excerpts_candidates_and_real_api(monkeypatch):
    """The oracle must see GROUND TRUTH (the explorer's real file bodies, candidate
    refs, and probed APIs) — not just a prose summary. This is the fix for the
    unwinnable-check bug: with `TextArea`'s real attrs in hand, the oracle would not
    invent `.value`. Regression-pins that excerpts/candidates/REAL APIs reach the prompt."""
    async def fake_probe(excerpts, terms, cwd, cancel):
        return "textual.widgets.TextArea public attrs: text, insert, focus"
    monkeypatch.setattr(_api_probe_mod, "probe_apis", fake_probe)
    # patch the symbol imported into the oracle module namespace too
    import poor_code.domain.harness.nodes.acceptance_oracle as oracle_mod
    monkeypatch.setattr(oracle_mod, "probe_apis", fake_probe)

    state = SessionState(
        requirement=Requirement(summary="switch prompt-input to a TextArea",
                                acceptance=("multiline input works",)),
        understanding=CodeContext(
            grounding=GroundingStatus.NOT_FOUND,
            summary="PromptBox currently composes an Input.",
            candidates=(CodeRef(file="src/ui/prompt_box.py", symbol="PromptBox.compose"),),
            excerpts=(FileExcerpt(
                path="src/ui/prompt_box.py",
                text="from textual.widgets import Input\nclass PromptBox: ..."),),
        ),
    )
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "src/ui/prompt_box.py" in prompt              # candidate ref
    assert "from textual.widgets import Input" in prompt  # verbatim excerpt body
    assert "REAL APIs" in prompt and "text, insert, focus" in prompt  # probed API


@pytest.mark.asyncio
async def test_oracle_prompt_carries_open_questions_and_incomplete_exploration():
    # P2 anti-evaporation: the interviewer's open_questions and the explorer's
    # not_found search_notes must reach the oracle, so it does not design a check that
    # pretends an unverified behaviour is settled.
    state = SessionState(
        requirement=Requirement(summary="multiline prompt",
                                acceptance=("works",),
                                open_questions=("is Enter submit or newline?",)),
        understanding=CodeContext(
            grounding=GroundingStatus.NOT_FOUND,
            search_notes="prompt_box.py _on_submit body was truncated; submit path unseen",
        ),
    )
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "is Enter submit or newline?" in prompt          # open question surfaced
    assert "submit path unseen" in prompt                   # incomplete-exploration note
    assert "INCOMPLETE EXPLORATION" in prompt


@pytest.mark.asyncio
async def test_oracle_system_requires_grounding_api_against_real_attrs():
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    system = llm.seen_messages[0]["content"].lower()
    assert "real apis" in system or "do not guess" in system
    # v2: grounding survives as naming the real attribute (e.g. `.text` not `.value`)
    assert ".value" in system or "real attribute" in system


@pytest.mark.asyncio
async def test_oracle_surfaces_repair_hint_forcefully():
    llm = FakeLLM({"checks": []})
    await AcceptanceOracle(llm).run(
        NodeContext(_state(repair_hint="a 13-byte file with no newline passes — wrong"),
                    cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "13-byte file with no newline" in prompt
    # the counterexample must be framed as something the redesign has to DEFEAT
    assert "counterexample" in prompt.lower()
    assert "fail" in prompt.lower()


@pytest.mark.asyncio
async def test_oracle_carries_status_confidence_evidence():
    llm = FakeLLM({"checks": [
        {"criterion": "avg_temp.txt is exactly 11.429",
         "command": "test \"$(cat avg_temp.txt)\" = 11.429",
         "status": "verified", "confidence": "high",
         "evidence": "read 247 rows, normalized 3 date formats, computed 11.429"},
        {"criterion": "rare edge value mapping is correct",
         "status": "unknown", "confidence": "low",
         "evidence": "could not derive expected mapping from source"}]})
    res = await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    c0, c1 = res.output.checks
    assert c0.status == "verified" and c0.confidence == "high"
    assert "11.429" in c0.evidence
    assert c1.status == "unknown"


@pytest.mark.asyncio
async def test_oracle_status_defaults_to_verified_when_omitted():
    # Back-compat: a check emitted without the new fields stays 'verified'.
    llm = FakeLLM({"checks": [{"criterion": "exact content", "command": "true"}]})
    res = await AcceptanceOracle(llm).run(NodeContext(_state(), cancel=asyncio.Event()))
    assert res.output.checks[0].status == "verified"
