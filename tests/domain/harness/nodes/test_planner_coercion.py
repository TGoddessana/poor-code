"""FM2: the planner must survive weak-model deformations — e.g. tasks array wrapped
as `{"task": [...]}` — by coercing the shape, not crashing with a raw ValidationError
(which terminated the whole run, repair count 0). Tests adapted to the new skeleton
schema (_SkeletonTaskOut: id, title, editable, depends_on)."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import StructuredOutputError
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import ProjectMap


def _planner():
    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    return Planner(llm=object(), project_map=pm)


def test_parse_coerces_tasks_emitted_as_singular_key_object():
    # Weak model wraps tasks list as {"task": [...]} instead of plain list.
    raw = '{"tasks":{"task":[{"id":"t1","title":"t","editable":["fib.py"],"depends_on":[]}]}}'
    plan = _planner().parse(raw)
    assert len(plan.tasks) == 1
    assert plan.tasks[0].title == "t"
    assert plan.tasks[0].edit_scope.editable == ("fib.py",)


def test_parse_coerces_editable_emitted_as_singular_key_object():
    # Weak model wraps editable list as {"file": [...]} instead of plain list.
    raw = '{"tasks":[{"id":"t1","title":"fib","editable":{"file":["fib.py"]},"depends_on":[]}]}'
    plan = _planner().parse(raw)
    assert len(plan.tasks) == 1
    assert plan.tasks[0].edit_scope.editable == ("fib.py",)


def test_parse_raises_structured_output_error_not_raw_validation_error():
    # tasks[].id is required; omitting it must surface as StructuredOutputError
    # (caught downstream as a recoverable LLM failure), never a raw ValidationError.
    with pytest.raises(StructuredOutputError):
        _planner().parse('{"tasks":[{"title":"no-id-field"}]}')
