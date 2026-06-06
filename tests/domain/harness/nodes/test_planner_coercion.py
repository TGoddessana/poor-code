"""FM2: the planner must survive the exact fibonacci-killer payload — a weak model
wrapping the steps array as `{"step": [...]}` — by coercing the shape, not crashing
with a raw ValidationError (which terminated the whole run, repair count 0)."""
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


def test_parse_coerces_steps_emitted_as_singular_key_object():
    raw = (
        '{"tasks":[{"title":"fib","purpose":"p",'
        '"edit_scope":{"editable":["fib.py"]},'
        '"how_to_validate":"python -c x",'
        '"steps":{"step":[{"kind":"impl","file":"fib.py","body":"def f(): pass",'
        '"run":"python -c x","expected":"PASS"}]}}]}'
    )
    plan = _planner().parse(raw)
    assert len(plan.tasks) == 1
    assert plan.tasks[0].steps[0].file == "fib.py"
    assert plan.tasks[0].steps[0].body == "def f(): pass"


def test_parse_coerces_tasks_emitted_as_singular_key_object():
    raw = '{"tasks":{"task":[{"title":"t","purpose":"p"}]}}'
    plan = _planner().parse(raw)
    assert len(plan.tasks) == 1
    assert plan.tasks[0].title == "t"


def test_parse_raises_structured_output_error_not_raw_validation_error():
    # tasks[].title is required; omitting it must surface as StructuredOutputError
    # (caught downstream as a recoverable LLM failure), never a raw ValidationError.
    with pytest.raises(StructuredOutputError):
        _planner().parse('{"tasks":[{"purpose":"p"}]}')
