"""FM1: a CREATE task (openssl /app/ssl/*, organization.json, any greenfield file)
was structurally impossible to pass plan_gate, because the weak model named the new
file in its steps but forgot to list it in edit_scope.editable, and the gate rejects
`step.file not in editable`. The fix computes the scope in CODE (planner) — editable
= declared editable ∪ the files the task's own steps write — and the gate stays dumb
('intelligence upstream, gate stays dumb')."""
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness.nodes.gates import PlanGate
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import SessionState


def _planner():
    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    return Planner(llm=object(), project_map=pm)


def test_to_task_unions_step_files_into_editable():
    raw = (
        '{"tasks":[{"title":"create cert","purpose":"p",'
        '"edit_scope":{"editable":[]},'
        '"how_to_validate":"test -f /app/ssl/cert.pem",'
        '"steps":[{"kind":"impl","file":"/app/ssl/cert.pem","body":"X",'
        '"run":"test -f /app/ssl/cert.pem","expected":"PASS"}]}]}'
    )
    plan = _planner().parse(raw)
    assert "/app/ssl/cert.pem" in plan.tasks[0].edit_scope.editable


def test_to_task_preserves_declared_editable_and_dedups():
    raw = (
        '{"tasks":[{"title":"t","purpose":"p",'
        '"edit_scope":{"editable":["a.py"]},'
        '"how_to_validate":"pytest -q",'
        '"steps":[{"kind":"impl","file":"a.py","body":"X","run":"pytest -q","expected":"PASS"},'
        '{"kind":"test","file":"b.py","body":"Y","run":"pytest -q","expected":"PASS"}]}]}'
    )
    editable = _planner().parse(raw).tasks[0].edit_scope.editable
    assert editable.count("a.py") == 1
    assert set(editable) == {"a.py", "b.py"}


def test_create_task_now_passes_plan_gate():
    raw = (
        '{"tasks":[{"title":"org json","purpose":"emit config",'
        '"edit_scope":{"editable":[]},'
        '"how_to_validate":"test -f organization.json",'
        '"steps":[{"kind":"impl","file":"organization.json","body":"{}",'
        '"run":"test -f organization.json","expected":"PASS"}]}]}'
    )
    plan = _planner().parse(raw)
    state = SessionState(plan=plan)
    assert PlanGate().check(state) is None  # previously: "outside editable scope"
