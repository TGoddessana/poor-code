import asyncio
import json
import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.session.models import (
    SessionState, Plan, Task, EditScope, Cursor, Phase, TaskStatus,
    Attempt, ValidationResult, ChangeRecord)
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.write import WriteTool
from poor_code.domain.tool.edit import EditTool
from poor_code.domain.tool.bash import BashTool
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class _WriteThenStopLLM:
    """Round 1: write `out.txt`. Round 2: stop (no tool calls)."""
    def __init__(self, content="hi"):
        self.calls = 0
        self._content = content
    async def stream(self, messages, tools, response_format=None):
        self.calls += 1
        if self.calls == 1:
            yield ToolCallStarted(call_id="w1", name="write")
            yield ToolCallInputDelta(
                call_id="w1",
                json_delta='{"path":"out.txt","content":"%s"}' % self._content)
            yield ToolCallEnded(call_id="w1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield TextDelta(text="done")
            yield FinishedReason(reason="stop")


def _tools():
    return ToolRegistry([WriteTool(), EditTool(), BashTool()])


class _BashThenStopLLM:
    """Round 1: run a bash command (big output). Round 2: capture messages, stop."""
    def __init__(self, command):
        self.calls = 0
        self._command = command
        self.round2_messages = None
    async def stream(self, messages, tools, response_format=None):
        self.calls += 1
        if self.calls == 1:
            yield ToolCallStarted(call_id="b1", name="bash")
            yield ToolCallInputDelta(
                call_id="b1", json_delta=json.dumps({"command": self._command}))
            yield ToolCallEnded(call_id="b1")
            yield FinishedReason(reason="tool_calls")
        else:
            self.round2_messages = messages
            yield TextDelta(text="done")
            yield FinishedReason(reason="stop")


class _RecordingSink:
    def __init__(self):
        self.finished = []
    def node_entered(self, *a, **k): pass
    def text_delta(self, *a, **k): pass
    def tool_started(self, *a, **k): pass
    def tool_finished(self, cid, result): self.finished.append(result)
    def tool_failed(self, *a, **k): pass


@pytest.mark.asyncio
async def test_implementer_clamps_large_tool_output_in_resent_messages(tmp_path):
    # 50k 'A's: small enough for one bash call, large enough to require clamping.
    llm = _BashThenStopLLM("head -c 50000 /dev/zero | tr '\\0' A")
    sink = _RecordingSink()
    await Implementer(llm, cwd=tmp_path, tools=_tools()).run(
        NodeContext(state=_state(), cancel=asyncio.Event(), sink=sink))
    tool_msgs = [m for m in llm.round2_messages if m.get("role") == "tool"]
    assert tool_msgs, "expected the tool result to be in the re-sent messages"
    content = tool_msgs[0]["content"]
    assert "elided" in content                    # clamped for the LLM
    # The latest round gets the larger budget (_LATEST_HEAD + _LATEST_TAIL = 8000 chars);
    # the bound is still far below the raw 50k — context growth is bounded.
    assert len(content) < 10000
    # the sink (display/log) still received the full output (>> the clamped copy)
    assert any(len(str(r)) > 25000 for r in sink.finished)


class _TwoBashThenStopLLM:
    """Round 1: bash b1 (big). Round 2: bash b2 (big). Round 3: capture messages, stop.
    Three rounds are needed to exercise demote: it only fires when a round LATER than
    the one being demoted arrives (a 2-round double early-returns before demote runs)."""
    def __init__(self, command):
        self.calls = 0
        self._command = command
        self.round3_messages = None
    async def stream(self, messages, tools, response_format=None):
        self.calls += 1
        if self.calls in (1, 2):
            cid = f"b{self.calls}"
            yield ToolCallStarted(call_id=cid, name="bash")
            yield ToolCallInputDelta(
                call_id=cid, json_delta=json.dumps({"command": self._command}))
            yield ToolCallEnded(call_id=cid)
            yield FinishedReason(reason="tool_calls")
        else:
            self.round3_messages = messages
            yield TextDelta(text="done")
            yield FinishedReason(reason="stop")


@pytest.mark.asyncio
async def test_demote_shrinks_earlier_round_when_a_newer_round_arrives(tmp_path):
    # b1 is round 1; once round 2 (b2) arrives it must be demoted to the standard clamp,
    # while b2 (now the latest) keeps the large budget. Guards the in-place mutation.
    llm = _TwoBashThenStopLLM("head -c 50000 /dev/zero | tr '\\0' A")
    await Implementer(llm, cwd=tmp_path, tools=_tools()).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    tool_msgs = {m["tool_call_id"]: m for m in llm.round3_messages if m.get("role") == "tool"}
    assert "b1" in tool_msgs and "b2" in tool_msgs
    b1, b2 = len(tool_msgs["b1"]["content"]), len(tool_msgs["b2"]["content"])
    assert "elided" in tool_msgs["b1"]["content"] and "elided" in tool_msgs["b2"]["content"]
    assert b1 < 3000          # demoted to standard budget (1200+800)
    assert b2 > 7000          # latest keeps the large budget (4000+4000)


def _state(attempts=()):
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("out.txt",)),
                              how_to_validate="test -f out.txt",
                              status=TaskStatus.ACTIVE, attempts=attempts),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t1"))


def _impl_state_with_one_task(cwd):
    """Planned SessionState with a single ACTIVE task and a cursor pointing at it —
    enough for Implementer.run to reach _loop. Mirrors the construction the other
    implementer tests use via _state(); `cwd` is accepted for parity with the
    characterization tests (the task's editable path is repo-relative)."""
    return _state()


@pytest.mark.asyncio
async def test_implementer_writes_file_and_emits_attempt(tmp_path):
    node = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert (tmp_path / "out.txt").read_text() == "hi"
    att = res.output
    assert isinstance(att, Attempt)
    assert att.adversarial_rounds == 0
    assert "out.txt" in att.patch.files
    assert "out.txt" in att.patch.diff


@pytest.mark.asyncio
async def test_implementer_refines_in_place_when_latest_has_no_run_result(tmp_path):
    node = Implementer(_WriteThenStopLLM(content="v2"), cwd=tmp_path, tools=_tools())
    prior = Attempt(id="t1-a1", patch=ChangeRecord(files=("out.txt",), diff="old"),
                    adversarial_rounds=0, run_result=None)
    res = await node.run(NodeContext(state=_state(attempts=(prior,)), cancel=asyncio.Event()))
    assert res.output.id == "t1-a1"               # same id → in-place refine
    assert res.output.adversarial_rounds == 1


@pytest.mark.asyncio
async def test_implementer_starts_new_attempt_after_runner_failure(tmp_path):
    node = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    failed = Attempt(id="t1-a1", patch=ChangeRecord(files=("out.txt",), diff="x"),
                     adversarial_rounds=2,
                     run_result=ValidationResult(command="c", exit_code=1, passed=False))
    res = await node.run(NodeContext(state=_state(attempts=(failed,)), cancel=asyncio.Event()))
    assert res.output.id == "t1-a2"               # new attempt id
    assert res.output.adversarial_rounds == 0


def test_prompt_renders_ordered_steps(tmp_path):
    from poor_code.domain.session.models import Step, StepKind
    step = Step(id="t1.s1", kind=StepKind.IMPL, file="x.py", anchor="end of file",
                body="def f():\n    return 1", run="pytest -q", expected="PASS")
    task = Task(id="t1", title="add f", purpose="p",
                edit_scope=EditScope(editable=("x.py",)),
                how_to_validate="pytest -q", steps=(step,))
    impl = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    prompt = impl._prompt(SessionState(), task)
    assert "STEPS (apply in order" in prompt
    assert "t1.s1" in prompt and "def f():" in prompt
    assert "run: pytest -q" in prompt and "expected: PASS" in prompt


def test_prompt_injects_real_api_digest(tmp_path):
    # Once probed (cached on the node), the real public API is handed to the model so it
    # writes against actual attributes (`TextArea.text`) instead of a recalled `.value`.
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("x.py",)), how_to_validate="pytest -q")
    impl = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    impl._api_digest = "textual.widgets.TextArea public attrs: text, insert, focus"
    prompt = impl._prompt(SessionState(), task)
    assert "REAL APIs" in prompt
    assert "text, insert, focus" in prompt


def test_prompt_omits_api_block_when_no_digest(tmp_path):
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("x.py",)), how_to_validate="pytest -q")
    impl = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    # _api_digest defaults to None (not yet probed) and may be "" (nothing groundable)
    assert impl._prompt(SessionState(), task).count("REAL APIs") == 0
    impl._api_digest = ""
    assert impl._prompt(SessionState(), task).count("REAL APIs") == 0


def test_prompt_surfaces_open_questions_and_incomplete_exploration(tmp_path):
    # P2: an unresolved question or a not_found exploration note must drive a READ here,
    # not evaporate. Routed into the implementer prompt as UNVERIFIED items.
    from poor_code.domain.session.models import (
        CodeContext, GroundingStatus, Requirement)
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("x.py",)), how_to_validate="pytest -q")
    impl = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    state = SessionState(
        requirement=Requirement(summary="s", open_questions=("which key submits?",)),
        understanding=CodeContext(grounding=GroundingStatus.NOT_FOUND,
                                  search_notes="submit handler body truncated"))
    prompt = impl._prompt(state, task)
    assert "UNVERIFIED" in prompt
    assert "which key submits?" in prompt
    assert "submit handler body truncated" in prompt


def test_prompt_no_unverified_block_when_grounded(tmp_path):
    # A GROUNDED/greenfield exploration with no open questions adds no noise.
    from poor_code.domain.session.models import CodeContext, GroundingStatus
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("x.py",)), how_to_validate="pytest -q")
    impl = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    state = SessionState(understanding=CodeContext(
        grounding=GroundingStatus.GREENFIELD, search_notes="n/a"))
    assert "UNVERIFIED" not in impl._prompt(state, task)


def test_prompt_injects_env_report(tmp_path):
    from poor_code.domain.session.models import EnvReport
    er = EnvReport(ready=True, test_command="python -m pytest -q",
                   install_steps=("pip install -e .[test]",), notes="numpy built")
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("x.py",)), how_to_validate="pytest -q")
    impl = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    prompt = impl._prompt(SessionState(env_report=er), task)
    assert "python -m pytest -q" in prompt
    assert "already" in prompt.lower()  # deps already installed — don't reinstall/fake


from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.harness.nodes.implementer import _LATEST_HEAD, _LATEST_TAIL


def test_latest_round_gets_bigger_budget_than_history():
    big = "X" * 30000
    latest = clamp_tool_output(big, head=_LATEST_HEAD, tail=_LATEST_TAIL)
    history = clamp_tool_output(big)
    assert len(latest) > len(history)   # the latest round preserves more than history


def test_prompt_omits_empty_purpose_and_validation(tmp_path):
    task = Task(id="t1", title="x", purpose="",
                edit_scope=EditScope(editable=("x.py",)), how_to_validate="")
    impl = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    prompt = impl._prompt(SessionState(), task)
    assert "PURPOSE:" not in prompt
    # The empty label line is gone; the bare word "VALIDATION" still appears in the
    # always-present orientation text (render_position), which is out of scope here.
    assert "VALIDATION (make this pass):" not in prompt
    assert "TASK: x" in prompt          # the task header itself still renders


def test_prompt_renders_purpose_and_validation_when_present(tmp_path):
    task = Task(id="t1", title="x", purpose="serve fib over HTTP",
                edit_scope=EditScope(editable=("x.py",)), how_to_validate="pytest -q")
    impl = Implementer(_WriteThenStopLLM(), cwd=tmp_path, tools=_tools())
    prompt = impl._prompt(SessionState(), task)
    assert "PURPOSE: serve fib over HTTP" in prompt
    assert "VALIDATION (make this pass): pytest -q" in prompt


from poor_code.domain.harness.nodes.implementer import _NUDGE


class _RepeatBashLLM:
    """Runs the SAME bash command every round (pure repeat). Records the messages
    list it was handed at the start of each round so tests can see injected nudges."""
    def __init__(self, rounds=4):
        self.calls = 0
        self.rounds = rounds
        self.seen: list[list[str]] = []
    async def stream(self, messages, tools, response_format=None):
        self.seen.append([str(m.get("content", "")) for m in messages])
        self.calls += 1
        if self.calls > self.rounds:
            yield TextDelta(text="done"); yield FinishedReason(reason="stop"); return
        yield ToolCallStarted(call_id=f"b{self.calls}", name="bash")
        yield ToolCallInputDelta(call_id=f"b{self.calls}", json_delta='{"command":"echo hi"}')
        yield ToolCallEnded(call_id=f"b{self.calls}")
        yield FinishedReason(reason="tool_calls")


class _ProgressBashLLM(_RepeatBashLLM):
    """Different bash command each round → no repeat, no no-op → no nudge."""
    async def stream(self, messages, tools, response_format=None):
        self.seen.append([str(m.get("content", "")) for m in messages])
        self.calls += 1
        if self.calls > self.rounds:
            yield TextDelta(text="done"); yield FinishedReason(reason="stop"); return
        yield ToolCallStarted(call_id=f"b{self.calls}", name="bash")
        yield ToolCallInputDelta(call_id=f"b{self.calls}", json_delta='{"command":"echo %d"}' % self.calls)
        yield ToolCallEnded(call_id=f"b{self.calls}")
        yield FinishedReason(reason="tool_calls")


class _RepeatWriteLLM(_RepeatBashLLM):
    """Writes IDENTICAL content every round → after round 1 the file is unchanged,
    so rounds 2+ are no-op writes (tree hash stays put)."""
    async def stream(self, messages, tools, response_format=None):
        self.seen.append([str(m.get("content", "")) for m in messages])
        self.calls += 1
        if self.calls > self.rounds:
            yield TextDelta(text="done"); yield FinishedReason(reason="stop"); return
        yield ToolCallStarted(call_id=f"w{self.calls}", name="write")
        yield ToolCallInputDelta(call_id=f"w{self.calls}", json_delta='{"path":"out.txt","content":"same"}')
        yield ToolCallEnded(call_id=f"w{self.calls}")
        yield FinishedReason(reason="tool_calls")


def _seen_has_nudge(llm) -> bool:
    return any(_NUDGE in c for round_msgs in llm.seen for c in round_msgs)


def _seen_nudge_count(llm) -> int:
    return sum(1 for c in (llm.seen[-1] if llm.seen else []) if _NUDGE in c)


@pytest.mark.asyncio
async def test_repeated_tool_call_injects_nudge(tmp_path):
    llm = _RepeatBashLLM(rounds=4)
    await Implementer(llm, cwd=tmp_path, tools=_tools()).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    assert _seen_has_nudge(llm)


@pytest.mark.asyncio
async def test_repeated_write_injects_nudge(tmp_path):
    llm = _RepeatWriteLLM(rounds=4)
    await Implementer(llm, cwd=tmp_path, tools=_tools()).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    assert _seen_has_nudge(llm)


class _NoopEditLLM(_RepeatBashLLM):
    """R1 writes a file; R2+ issue edits with DISTINCT args whose old_string never
    matches → the edit errors, the file is unchanged → no-op detected via the TREE
    branch (sig differs every round, so the repeat branch never fires)."""
    async def stream(self, messages, tools, response_format=None):
        self.seen.append([str(m.get("content", "")) for m in messages])
        self.calls += 1
        if self.calls > self.rounds:
            yield TextDelta(text="done"); yield FinishedReason(reason="stop"); return
        if self.calls == 1:
            yield ToolCallStarted(call_id="w1", name="write")
            yield ToolCallInputDelta(call_id="w1", json_delta='{"path":"out.txt","content":"AAA"}')
            yield ToolCallEnded(call_id="w1")
        else:
            yield ToolCallStarted(call_id=f"e{self.calls}", name="edit")
            yield ToolCallInputDelta(
                call_id=f"e{self.calls}",
                json_delta='{"path":"out.txt","old_string":"ZZZ%d","new_string":"QQQ%d"}'
                           % (self.calls, self.calls))
            yield ToolCallEnded(call_id=f"e{self.calls}")
        yield FinishedReason(reason="tool_calls")


@pytest.mark.asyncio
async def test_noop_edit_injects_nudge_via_tree_branch(tmp_path):
    # distinct args each round → repeat branch never fires; the failed edit leaves the
    # file unchanged → only the (wrote and cur_tree == last_tree) no-op branch can nudge.
    llm = _NoopEditLLM(rounds=4)
    await Implementer(llm, cwd=tmp_path, tools=_tools()).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    assert _seen_has_nudge(llm)


@pytest.mark.asyncio
async def test_real_progress_does_not_nudge(tmp_path):
    llm = _ProgressBashLLM(rounds=4)
    await Implementer(llm, cwd=tmp_path, tools=_tools()).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    assert not _seen_has_nudge(llm)


@pytest.mark.asyncio
async def test_nudge_is_deduped_not_every_round(tmp_path):
    llm = _RepeatBashLLM(rounds=4)
    await Implementer(llm, cwd=tmp_path, tools=_tools()).run(
        NodeContext(state=_state(), cancel=asyncio.Event()))
    n = _seen_nudge_count(llm)
    assert 1 <= n < 4


@pytest.mark.asyncio
async def test_latest_round_keeps_big_budget_prior_demoted(tmp_path, monkeypatch):
    """Round N's tool output is clamped with the big budget; once round N+1 lands,
    round N is demoted to the standard clamp."""
    from poor_code.domain.harness.nodes import implementer as impl_mod
    monkeypatch.setattr(impl_mod, "_LATEST_HEAD", 10)
    monkeypatch.setattr(impl_mod, "_LATEST_TAIL", 10)
    big = "X" * 400
    from pydantic import BaseModel
    class _ReadArgs(BaseModel):
        path: str = ""
    class _ReadBigTool:
        id = "read"; description = "x"; params = _ReadArgs
        async def execute(self, args, ctx):
            class R: output = big
            return R()
    from poor_code.provider.events import (
        ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason)
    seen_lengths = []
    class _LLM:
        def __init__(self): self.round = 0
        async def stream(self, messages, tools, response_format=None):
            self.round += 1
            seen_lengths.append([len(m["content"]) for m in messages if m.get("role") == "tool"])
            if self.round <= 2:
                cid = f"r{self.round}"
                yield ToolCallStarted(call_id=cid, name="read")
                yield ToolCallInputDelta(call_id=cid, json_delta='{"path":"%d"}' % self.round)
                yield ToolCallEnded(call_id=cid)
                yield FinishedReason(reason="tool_calls")
            else:
                yield FinishedReason(reason="stop")
    from poor_code.domain.tool.registry import ToolRegistry
    node = Implementer(_LLM(), cwd=tmp_path, tools=ToolRegistry([_ReadBigTool()]))
    state = _impl_state_with_one_task(tmp_path)
    await node.run(NodeContext(state=state, cancel=asyncio.Event()))
    # At round 3's call: round-1 (older) demoted to the STANDARD clamp, round-2 (freshest)
    # carries the BIG-budget clamp. Assert each tool message exactly matches the clamp it
    # was supposed to get — this is the demotion invariant, independent of which absolute
    # budget happens to be larger (here _LATEST_* is monkeypatched to 10/10, BELOW the
    # standard 1200/800, so the demoted-older message is in fact LONGER; a strict
    # last[0] < last[1] would only hold when the big budget exceeds the standard one).
    last = seen_lengths[-1]
    assert len(last) == 2
    standard_len = len(clamp_tool_output(big))                       # round-1, demoted
    big_len = len(clamp_tool_output(big, head=10, tail=10))          # round-2, freshest
    assert standard_len != big_len                                   # the two budgets differ here
    assert last[0] == standard_len and last[1] == big_len


@pytest.mark.asyncio
async def test_noop_write_triggers_nudge_once(tmp_path):
    """A write that changes no file (tree hash unchanged) appends _NUDGE exactly once
    (non-consecutively)."""
    from poor_code.domain.harness.nodes import implementer as impl_mod
    from pydantic import BaseModel
    class _WArgs(BaseModel):
        path: str = ""; content: str = ""
    class _NoopWrite:
        id = "write"; description = "x"; params = _WArgs
        async def execute(self, args, ctx):
            class R: output = "wrote (no change)"   # never touches the tree
            return R()
    from poor_code.provider.events import (
        ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason)
    nudges = []
    class _LLM:
        def __init__(self): self.round = 0
        async def stream(self, messages, tools, response_format=None):
            self.round += 1
            nudges.append(sum(1 for m in messages
                              if m.get("role") == "user" and impl_mod._NUDGE in m["content"]))
            if self.round <= 3:
                cid = f"w{self.round}"
                yield ToolCallStarted(call_id=cid, name="write")
                yield ToolCallInputDelta(call_id=cid, json_delta='{"path":"a","content":"x"}')
                yield ToolCallEnded(call_id=cid)
                yield FinishedReason(reason="tool_calls")
            else:
                yield FinishedReason(reason="stop")
    from poor_code.domain.tool.registry import ToolRegistry
    node = Implementer(_LLM(), cwd=tmp_path, tools=ToolRegistry([_NoopWrite()]))
    state = _impl_state_with_one_task(tmp_path)
    await node.run(NodeContext(state=state, cancel=asyncio.Event()))
    assert nudges[-1] >= 1   # at least one nudge appeared (stuck fired, non-consecutive)
