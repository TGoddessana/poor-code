"""VerifierNode — the observation-grounded adversarial verifier that replaces the
bash-check chain. It runs an observe tool loop (here the fake LLM observes nothing and
stops), then emits a verdict that maps to advance(done) / repair_impl / repair_plan, with
a LOOSENED authority: at the attempt cap it accepts best-effort rather than abandoning."""
import asyncio
import json
from dataclasses import replace

import pytest

from poor_code.domain.harness.node import NodeContext, StructuredOutputError
from poor_code.domain.harness.nodes.execution import MAX_ATTEMPTS
from poor_code.domain.harness.nodes.verifier import VerifierNode, _OBSERVE_SYSTEM
from poor_code.domain.harness.subgraphs.implement_loop import _verifier_tools
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Attempt, ChangeRecord, Cursor, Layer, Phase,
    Plan, Requirement, SessionState, Task, TaskCompleted, TaskStatus, VerdictKind,
)
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


_BACKED = [{"criterion": "empty input shows an error",
            "observed": "ran run_shell('') and saw ValueError raised", "satisfied": True}]


class _VerifierLLM:
    """Two-phase fake: in the observe loop (tools = bash/read/...) it observes nothing
    and stops; in the judge phase (tool 'judge') it emits the scripted verdict. `checks`
    supplies the per-criterion observation evidence the leniency guard requires."""
    def __init__(self, verdict, hint="because observed", checks=None):
        payload = {"verdict": verdict, "hint": hint}
        if checks is not None:
            payload["checks"] = checks
        self._args = json.dumps(payload)
        self.seen = None

    async def stream(self, messages, tools, response_format=None):
        name = tools[0]["function"]["name"]
        if name == "judge":
            self.seen = messages
            yield ToolCallStarted(call_id="j1", name="judge")
            yield ToolCallInputDelta(call_id="j1", json_delta=self._args)
            yield ToolCallEnded(call_id="j1")
            yield FinishedReason(reason="tool_calls")
        else:  # observe phase — look at nothing, stop immediately
            yield TextDelta(text="observed enough")
            yield FinishedReason(reason="stop")


def _state(*, n_attempts=1, adv_rounds=0):
    attempts = tuple(
        Attempt(id=f"t1-a{i+1}", patch=ChangeRecord(files=("a.py",), diff="d"),
                adversarial_rounds=(adv_rounds if i == n_attempts - 1 else 0))
        for i in range(n_attempts))
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="A", purpose="p",
                              status=TaskStatus.ACTIVE, attempts=attempts),)),
        acceptance=AcceptanceSpec(checks=(
            AcceptanceCheck(criterion="empty input shows an error"),)),
        requirement=Requirement(summary="do X", acceptance=("X works",)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="verifier",
                      task_id="t1", attempt_id=attempts[-1].id))


def _node(llm):
    return VerifierNode(llm, cwd=".", tools=_verifier_tools())


def _ctx(state):
    return NodeContext(state=state, cancel=asyncio.Event())


def test_name_is_verifier():
    assert _node(_VerifierLLM("advance")).name == "verifier"


def test_observe_system_forbids_fixture_destruction_and_urges_scratch_tests():
    # E-poisoning fix: the verifier must NEVER mutate the task's real inputs to probe an
    # edge case (that poisons the graded artifact / deletes user data); it must instead
    # write a throwaway test in $TMPDIR. Pin both halves of that guardrail.
    s = _OBSERVE_SYSTEM.lower()
    # never destroy real inputs (names the destructive ops it must avoid)
    assert "never destroy" in s
    for op in ("overwrite", "truncate", "replace", "corrupt"):
        assert op in s
    # positively: write a scratch/throwaway test in $TMPDIR for edge cases
    assert "$tmpdir" in s
    assert "edge case" in s
    assert "throwaway test" in s or "small throwaway test" in s


def test_observe_system_rejects_fabricated_output():
    # sqlite frontier: structurally-valid but INVENTED output (placeholder rows) must not
    # pass on structure alone — the verifier must trace output back to the real source.
    s = _OBSERVE_SYSTEM.lower()
    assert "fabricat" in s
    assert "trace the output back to the source" in s or "trace" in s
    assert "structure alone" in s or "structurally valid" in s


@pytest.mark.asyncio
async def test_advance_with_observation_evidence_marks_done():
    r = await _node(_VerifierLLM("advance", checks=_BACKED)).run(_ctx(_state()))
    assert r.branch == "done"
    assert isinstance(r.output, TaskCompleted) and r.output.task_id == "t1"


@pytest.mark.asyncio
async def test_advance_without_observation_is_downgraded_to_repair():
    # Leniency guard: an 'advance' not backed by per-criterion observed evidence (no checks,
    # or a check left unsatisfied/unobserved) must NOT pass — it becomes repair_impl.
    r = await _node(_VerifierLLM("advance")).run(_ctx(_state()))  # no checks
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.IMPLEMENTATION
    r2 = await _node(_VerifierLLM("advance", checks=[
        {"criterion": "x", "observed": "", "satisfied": True}])).run(_ctx(_state()))  # observed empty
    assert r2.verdict.kind is VerdictKind.REPAIR


@pytest.mark.asyncio
async def test_repair_impl_below_cap():
    r = await _node(_VerifierLLM("repair_impl", hint="empty input crashed")).run(_ctx(_state()))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.IMPLEMENTATION
    assert "empty input crashed" in r.verdict.hint


@pytest.mark.asyncio
async def test_repair_plan_bubbles_to_plan_layer():
    r = await _node(_VerifierLLM("repair_plan", hint="wrong files")).run(_ctx(_state()))
    assert r.verdict.kind is VerdictKind.REPAIR
    assert r.verdict.layer is Layer.PLAN


@pytest.mark.asyncio
async def test_at_cap_accepts_best_effort_instead_of_abandoning():
    # Loosened authority: at the refinement cap (adversarial_rounds) a repair_impl verdict
    # does NOT abandon — it accepts best-effort and moves on (no rigid park/abandon).
    r = await _node(_VerifierLLM("repair_impl")).run(_ctx(_state(adv_rounds=MAX_ATTEMPTS)))
    assert r.branch == "done"
    assert isinstance(r.output, TaskCompleted)


def test_parse_rejects_unknown_verdict():
    with pytest.raises(StructuredOutputError):
        _node(None).parse('{"verdict": "ADVANCE", "hint": "x"}')


@pytest.mark.asyncio
async def test_observe_prompt_carries_criteria():
    llm = _VerifierLLM("advance")
    await _node(llm).run(_ctx(_state()))
    # the judge phase sees the observation history, which began with the criteria prompt
    blob = "\n".join(str(m.get("content", "")) for m in llm.seen)
    assert "empty input shows an error" in blob   # the criterion reached the verifier


class _RecordingSink:
    """Captures node_context(...) calls so a test can read what the verifier dumped.
    Every other sink method (thinking deltas, tool events the dispatch path emits) is a
    no-op via __getattr__."""
    def __init__(self):
        self.contexts = []  # list[(node, phase, messages)]

    def node_context(self, node, phase, messages):
        self.contexts.append((node, phase, messages))

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _ctx_with_sink(state, sink):
    return NodeContext(state=state, cancel=asyncio.Event(), sink=sink)


@pytest.mark.asyncio
async def test_verdict_trace_is_emitted_for_post_mortem():
    # Diagnostic instrumentation: after judging, the verifier dumps a 'verifier:verdict'
    # record carrying the observe transcript + the per-criterion checks + raw/final verdict.
    # This is the artifact that lets a false_accept be classified (weak criteria vs
    # unobserved vs rubber-stamped vs fabricated-evidence) instead of guessed.
    sink = _RecordingSink()
    await _node(_VerifierLLM("advance", checks=_BACKED)).run(_ctx_with_sink(_state(), sink))
    verdicts = [c for c in sink.contexts if c[0] == "verifier:verdict"]
    assert len(verdicts) == 1
    _, _, messages = verdicts[0]
    record = json.loads(messages[-1]["content"])
    assert record["raw_verdict"] == "advance"
    assert record["final_verdict"] == "advance"
    assert record["leniency_guard_fired"] is False
    assert record["checks"] == _BACKED


@pytest.mark.asyncio
async def test_verdict_trace_records_leniency_guard_downgrade():
    # When the guard turns a bare 'advance' into repair_impl, the trace must show BOTH
    # the model's raw verdict and that the guard fired — the signal that separates a
    # rubber-stamp (model said advance) from an honest repair.
    sink = _RecordingSink()
    await _node(_VerifierLLM("advance")).run(_ctx_with_sink(_state(), sink))  # no checks
    record = json.loads(
        [c for c in sink.contexts if c[0] == "verifier:verdict"][0][2][-1]["content"])
    assert record["raw_verdict"] == "advance"
    assert record["final_verdict"] == "repair_impl"
    assert record["leniency_guard_fired"] is True


def _state_with_unknown():
    s = _state()
    return replace(s, acceptance=AcceptanceSpec(checks=(
        AcceptanceCheck(criterion="core behaviour works", status="verified"),
        AcceptanceCheck(criterion="hard value is exact", status="unknown",
                        evidence="oracle could not derive expected value"))))


@pytest.mark.asyncio
async def test_unknown_criterion_does_not_block_advance():
    # Only the verified criterion must be observed-and-satisfied; the 'unknown' one is
    # advisory (the oracle abstained) and must NOT force repair.
    checks = [{"criterion": "core behaviour works",
               "observed": "ran prog, saw correct output", "satisfied": True}]
    r = await _node(_VerifierLLM("advance", checks=checks)).run(_ctx(_state_with_unknown()))
    assert r.branch == "done"


@pytest.mark.asyncio
async def test_unknown_criterion_is_surfaced_in_observe_prompt():
    node = _node(_VerifierLLM("advance"))
    s = _state_with_unknown()
    prompt = node._observe_prompt(s, s.plan.tasks[0])
    assert "advisory" in prompt.lower() or "unknown" in prompt.lower()
