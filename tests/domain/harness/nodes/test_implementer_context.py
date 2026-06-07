from pathlib import Path

from poor_code.domain.harness.nodes.implementer import Implementer, _SYSTEM
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Cursor, EditScope, Phase, Plan, Request,
    RequestKind, Requirement, SessionState, Task, TaskStatus)
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
