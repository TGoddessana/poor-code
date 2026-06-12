from pathlib import Path

from poor_code.domain.harness.nodes.implementer import Implementer, _SYSTEM
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Attempt, ChangeRecord, CodeRef, Cursor,
    EditScope, Phase, Plan, Request, RequestKind, Requirement, SessionState,
    Task, TaskContext, TaskStatus, ValidationResult)
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.write import WriteTool


def _node():
    return Implementer(llm=None, cwd=Path("."), tools=ToolRegistry([WriteTool()]))


def _state():
    task = Task(id="t2", title="server.js", purpose="serve fib",
                description="http server", edit_scope=EditScope(editable=("server.js",)),
                how_to_validate="curl -s localhost:3000/fib/10 | grep -q 55",
                status=TaskStatus.ACTIVE)
    return SessionState(
        request=Request(raw_text="Build a Node fib server on :3000", kind=RequestKind.ENGINEERING),
        requirement=Requirement(summary="Node HTTP server returning BigInt fib"),
        plan=Plan(tasks=(task,)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"))


def test_prompt_includes_original_request_and_overall_goal():
    state = _state()
    task = state.plan.tasks[0]
    prompt = _node()._prompt(state, task)
    assert "ORIGINAL REQUEST:" in prompt
    assert "Build a Node fib server on :3000" in prompt
    assert "OVERALL GOAL:" in prompt
    assert "Node HTTP server returning BigInt fib" in prompt
    assert "curl -s localhost:3000/fib/10" in prompt  # validation still present


def test_system_prompt_forbids_stubs():
    assert "stub" in _SYSTEM.lower()
    assert "placeholder" in _SYSTEM.lower()


def test_implementer_sees_acceptance_and_ledger():
    """build_messages (via _prompt) must include full acceptance spec + ledger as
    stable cache-friendly prefix, and the plan_md task section as the task body."""
    task = Task(id="t2", title="fib server", purpose="serve fib",
                description="http server", edit_scope=EditScope(editable=("server.py",)),
                how_to_validate="curl -s localhost:3000/fib/10 | grep -q 55",
                status=TaskStatus.ACTIVE)
    state = SessionState(
        request=Request(raw_text="Build a fib server on :3000", kind=RequestKind.ENGINEERING),
        requirement=Requirement(summary="Node HTTP server returning fib"),
        plan=Plan(tasks=(task,), plan_md="## t2: fib-server\nImplement GET /fib/:n"),
        acceptance=AcceptanceSpec(checks=(
            AcceptanceCheck(criterion="n=10 -> 55",
                            command="curl -s localhost:3000/fib/10 | grep -q 55"),
        )),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"),
    )
    prompt = _node()._prompt(state, task)
    # acceptance spec present
    assert "n=10 -> 55" in prompt
    # ledger present (sentinel for empty ledger)
    assert "completed work" in prompt.lower() or "no completed work" in prompt.lower()
    # plan_md task section present
    assert "## t2" in prompt
    assert "Implement GET /fib/:n" in prompt


def test_prompt_renders_snippet_as_ground_truth():
    task = Task(id="t2", title="x", purpose="p",
                edit_scope=EditScope(editable=("server.py",)),
                how_to_validate="true", status=TaskStatus.ACTIVE,
                context=TaskContext(snippet="--- server.py [EDITABLE] ---\ndef fib(n): return n"))
    state = SessionState(
        plan=Plan(tasks=(task,)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"))
    prompt = _node()._prompt(state, task)
    assert "ground truth" in prompt
    assert "def fib(n): return n" in prompt          # the body reaches the implementer


def test_prompt_falls_back_to_ref_list_without_snippet():
    task = Task(id="t2", title="x", purpose="p",
                edit_scope=EditScope(editable=("server.py",)),
                how_to_validate="true", status=TaskStatus.ACTIVE,
                context=TaskContext(refs=(CodeRef(file="server.py", symbol="fib"),), snippet=None))
    state = SessionState(
        plan=Plan(tasks=(task,)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"))
    prompt = _node()._prompt(state, task)
    assert "RELEVANT CODE" in prompt
    assert "server.py::fib" in prompt


def test_system_prompt_allows_reading_not_forbids():
    assert "not a reader" not in _SYSTEM.lower()      # the false double-bind is gone
    assert "bash" in _SYSTEM.lower()                   # it may read with bash
    assert "editable" in _SYSTEM.lower()               # writes confined to EDITABLE


def test_prompt_injects_previous_failed_attempt_diff():
    failed = Attempt(id="t2-a1",
                     patch=ChangeRecord(files=("server.py",), diff="- old\n+ broken line"),
                     run_result=ValidationResult(command="true", exit_code=1, passed=False))
    task = Task(id="t2", title="x", purpose="p",
                edit_scope=EditScope(editable=("server.py",)),
                how_to_validate="true", status=TaskStatus.ACTIVE, attempts=(failed,))
    state = SessionState(
        plan=Plan(tasks=(task,)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"))
    prompt = _node()._prompt(state, task)
    assert "PREVIOUS ATTEMPT" in prompt
    assert "+ broken line" in prompt


def test_prompt_no_previous_attempt_block_on_first_try():
    task = Task(id="t2", title="x", purpose="p",
                edit_scope=EditScope(editable=("server.py",)),
                how_to_validate="true", status=TaskStatus.ACTIVE)
    state = SessionState(
        plan=Plan(tasks=(task,)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"))
    assert "PREVIOUS ATTEMPT" not in _node()._prompt(state, task)


def test_prompt_renders_both_snippet_and_previous_attempt_on_retry():
    # The real retry state: context bodies AND the prior failed diff both present.
    failed = Attempt(id="t2-a1",
                     patch=ChangeRecord(files=("server.py",), diff="- old\n+ broken line"),
                     run_result=ValidationResult(command="true", exit_code=1, passed=False))
    task = Task(id="t2", title="x", purpose="p",
                edit_scope=EditScope(editable=("server.py",)),
                how_to_validate="true", status=TaskStatus.ACTIVE, attempts=(failed,),
                context=TaskContext(snippet="--- server.py [EDITABLE] ---\ndef fib(n): return n"))
    state = SessionState(
        plan=Plan(tasks=(task,)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t2"))
    prompt = _node()._prompt(state, task)
    assert "ground truth" in prompt               # snippet block present
    assert "def fib(n): return n" in prompt       # body present
    assert "PREVIOUS ATTEMPT" in prompt           # retry block present
    assert "+ broken line" in prompt              # prior diff present
    assert prompt.index("ground truth") < prompt.index("PREVIOUS ATTEMPT")  # RELEVANT CODE precedes it
