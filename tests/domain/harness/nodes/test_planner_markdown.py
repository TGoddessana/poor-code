import json
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import ProjectMap


def _planner():
    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    return Planner(llm=None, project_map=pm)


def test_blank_id_task_dep_uses_resolved_id():
    # Task with a blank id (weak-model emission) resolves to t1; its own dependency
    # must record the RESOLVED task_id, never "".
    args = json.dumps({"plan_md": "## t1\n## t2", "tasks": [
        {"id": "", "title": "a", "editable": ["a.py"], "depends_on": ["t2"]},
        {"id": "t2", "title": "b", "editable": ["b.py"], "depends_on": []},
    ]})
    plan = _planner().parse(args)
    ids = {t.id for t in plan.tasks}
    assert "" not in ids                       # blank resolved away
    assert len(plan.deps) == 1
    d = plan.deps[0]
    assert d.task_id != "" and d.task_id in ids
    assert d.depends_on == "t2"

def test_unknown_dependency_is_kept_for_plan_gate():
    # A depends_on referencing a non-emitted task id must survive parse (raw),
    # so plan_gate can flag it — parse must NOT silently drop it.
    args = json.dumps({"plan_md": "## t1", "tasks": [
        {"id": "t1", "title": "a", "editable": ["a.py"], "depends_on": ["t99"]},
    ]})
    plan = _planner().parse(args)
    assert any(d.depends_on == "t99" for d in plan.deps)


def test_parse_md_and_skeleton():
    args = json.dumps({
        "plan_md": "## t1: server.py — /fib handler\n## t2: server.py — validation",
        "tasks": [
            {"id": "t1", "title": "fib handler", "editable": ["server.py"], "depends_on": []},
            {"id": "t2", "title": "validation", "editable": ["server.py"], "depends_on": ["t1"]},
        ],
    })
    plan = _planner().parse(args)
    assert plan.plan_md.startswith("## t1")
    assert [t.id for t in plan.tasks] == ["t1", "t2"]
    assert plan.tasks[0].edit_scope.editable == ("server.py",)
    assert plan.tasks[0].steps == ()            # steps no longer required
    assert plan.tasks[0].how_to_validate == ""  # demoted
    assert any(d.task_id == "t2" and d.depends_on == "t1" for d in plan.deps)
