import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.acceptance_oracle import (
    AcceptanceOracle, _AUTHOR_SYSTEM, _SYSTEM)
from poor_code.domain.session.models import (
    AcceptanceSpec, CodeContext, CodeRef, FileExcerpt, GroundingStatus, Request,
    RequestKind, Requirement, SessionState,
)
from poor_code.domain.harness import api_probe as _api_probe_mod
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.grep import GrepTool
from poor_code.domain.tool.glob import GlobTool
from poor_code.domain.tool.list import ListTool
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
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


def test_author_system_drives_tools_and_is_non_destructive():
    s = _AUTHOR_SYSTEM.lower()
    # authors an executable test by computing, not recalling
    assert "compute" in s or "derive" in s
    assert "$tmpdir" in s
    # discrimination self-check: the test must FAIL on a wrong/stub implementation
    assert "stub" in s or "wrong implementation" in s
    assert "discriminat" in s or "must fail" in s
    # honest abstention floor
    assert "unknown" in s
    # non-destructive (E-guard) + independence (no candidate to run yet)
    for op in ("overwrite", "truncate", "replace"):
        assert op in s


def test_emit_system_mentions_status_and_evidence():
    s = _SYSTEM.lower()
    assert "status" in s and "unknown" in s
    assert "evidence" in s


class _TwoPhaseLLM:
    """Authoring phase: emit one bash call then stop. Emit phase (tool 'emit_acceptance'):
    emit the scripted spec, and capture the messages so we can assert the authoring
    observations were threaded in as evidence."""
    def __init__(self, payload):
        self._args = json.dumps(payload)
        self.emit_messages = None
        self._authored = False

    async def stream(self, messages, tools, response_format=None):
        name = tools[0]["function"]["name"]
        if name == "emit_acceptance":
            self.emit_messages = messages
            yield ToolCallStarted(call_id="e1", name="emit_acceptance")
            yield ToolCallInputDelta(call_id="e1", json_delta=self._args)
            yield ToolCallEnded(call_id="e1")
            yield FinishedReason(reason="tool_calls")
        elif not self._authored:           # first authoring round: run one tool
            self._authored = True
            yield ToolCallStarted(call_id="a1", name="bash")
            yield ToolCallInputDelta(call_id="a1", json_delta=json.dumps({"command": "echo 11.429"}))
            yield ToolCallEnded(call_id="a1")
            yield FinishedReason(reason="tool_calls")
        else:                               # second authoring round: stop
            yield TextDelta(text="worked it out")
            yield FinishedReason(reason="stop")


def _oracle_tools():
    return ToolRegistry([BashTool(), ReadTool(), GrepTool(), GlobTool(), ListTool()])


@pytest.mark.asyncio
async def test_oracle_runs_authoring_loop_then_emits(tmp_path):
    llm = _TwoPhaseLLM({"checks": [
        {"criterion": "avg is 11.429", "command": "true",
         "status": "verified", "confidence": "high", "evidence": "echo 11.429 -> 11.429"}]})
    node = AcceptanceOracle(llm, cwd=tmp_path, tools=_oracle_tools())
    res = await node.run(NodeContext(_state(), cancel=asyncio.Event()))
    assert res.output.checks[0].status == "verified"
    # authoring observations (the bash round) were threaded into the emit call
    blob = json.dumps(llm.emit_messages)
    assert "echo 11.429" in blob


@pytest.mark.asyncio
async def test_oracle_without_tools_still_emits(tmp_path):
    # Back-compat: constructed without tools (greenfield / no inputs), the 1-shot FakeLLM
    # must still produce a spec — the authoring loop is skipped when no tools are present.
    llm = FakeLLM({"checks": [{"criterion": "exact content", "command": "true"}]})
    res = await AcceptanceOracle(llm, cwd=tmp_path).run(NodeContext(_state(), cancel=asyncio.Event()))
    assert res.output.checks[0].criterion == "exact content"
