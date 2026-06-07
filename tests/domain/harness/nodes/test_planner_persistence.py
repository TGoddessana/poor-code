"""The planner system prompt must describe the markdown-first, skeleton-output design
and must not instruct the planner to emit code steps (those belong to the implementer)."""
from poor_code.domain.harness.nodes.planner import _SYSTEM


def test_planner_system_has_no_kill_worldview():
    assert "kill" not in _SYSTEM.lower()


def test_planner_system_teaches_markdown_plan():
    s = _SYSTEM.lower()
    assert "plan_md" in s
    assert "markdown" in s


def test_planner_system_delegates_steps_to_implementer():
    s = _SYSTEM.lower()
    # The implementer, not the planner, derives concrete steps.
    assert "implementer" in s
    assert "steps" not in s or "derive concrete steps" in s
