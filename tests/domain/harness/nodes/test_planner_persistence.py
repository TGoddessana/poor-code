"""The planner must stop emitting start+kill validation. Services are launched and
LEFT RUNNING by the implementer; validation is a bare probe against the live instance."""
from poor_code.domain.harness.nodes.planner import _SYSTEM


def test_planner_system_has_no_kill_worldview():
    assert "kill" not in _SYSTEM.lower()


def test_planner_system_teaches_bare_probe_and_leave_running():
    s = _SYSTEM.lower()
    assert "bare probe" in s
    assert "running" in s  # "leaves it running" / "already-running service"
