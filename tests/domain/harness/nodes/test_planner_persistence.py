"""The planner system prompt must describe the markdown-first, skeleton-output design
with complete code-ordered TDD steps that the implementer applies."""
from poor_code.domain.harness.nodes.planner import _SYSTEM


def test_planner_system_has_no_kill_worldview():
    assert "kill" not in _SYSTEM.lower()


def test_planner_system_teaches_markdown_plan():
    s = _SYSTEM.lower()
    assert "plan_md" in s
    assert "markdown" in s


def test_planner_system_says_implementer_applies_steps():
    s = _SYSTEM.lower()
    # The planner authors the steps; the implementer applies them.
    assert "implementer" in s
    assert "applies your steps" in s
