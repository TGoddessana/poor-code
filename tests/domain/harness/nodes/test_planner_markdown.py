import json
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import ProjectMap


def _planner():
    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    return Planner(llm=None, project_map=pm)


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
