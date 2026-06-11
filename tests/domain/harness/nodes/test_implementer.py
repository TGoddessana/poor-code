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


def _state(attempts=()):
    return SessionState(
        plan=Plan(tasks=(Task(id="t1", title="x", purpose="p",
                              edit_scope=EditScope(editable=("out.txt",)),
                              how_to_validate="test -f out.txt",
                              status=TaskStatus.ACTIVE, attempts=attempts),)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t1"))


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
