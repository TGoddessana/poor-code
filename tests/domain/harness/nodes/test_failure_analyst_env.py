"""failure_analyst must see the environment and, on a 'command not found' style
failure, force a switch to an available runtime — not let the implementer retry
the same absent one (gpt-5.4-mini wrote a Node server 6× on a node-less box)."""
from poor_code.domain.harness.nodes.failure_analyst import FailureAnalyst, _SYSTEM
from poor_code.domain.session.models import (
    Attempt, ChangeRecord, CodeContext, Cursor, EditScope, Phase, Plan, SessionState,
    Task, ValidationResult,
)

_ENV = "ENV: python3 yes; NOT FOUND: node"


def _state():
    rr = ValidationResult(command="node server.js", exit_code=127,
                          passed=False, output="/bin/sh: 1: node: not found")
    attempt = Attempt(id="t1-a1", patch=ChangeRecord(files=("server.js",), diff="+ server.js"),
                      adversarial_rounds=0, run_result=rr)
    task = Task(id="t1", title="impl server", purpose="p",
                edit_scope=EditScope(editable=("server.js",)),
                attempts=(attempt,))
    return SessionState(
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="failure_analyst", task_id="t1"),
        understanding=CodeContext(environment=_ENV),
        plan=Plan(tasks=(task,), deps=()),
    )


def test_failure_analyst_prompt_includes_environment():
    msgs = FailureAnalyst(llm=None).build_messages(_state())
    assert any(_ENV in m["content"] for m in msgs)


def test_failure_analyst_system_has_runtime_switch_rule():
    s = _SYSTEM.lower()
    assert "not found" in s
    assert "available" in s or "switch" in s
