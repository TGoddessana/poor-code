"""The implementer must know to launch services in the background, leave them running,
and adapt (not blindly retry) when a launch fails on a bound port."""
from poor_code.domain.harness.nodes.implementer import _SYSTEM


def test_implementer_system_teaches_background_launch():
    s = _SYSTEM.lower()
    assert "background" in s
    assert "running" in s  # "leave it running"


def test_implementer_system_teaches_port_conflict_adaptation():
    s = _SYSTEM.lower()
    assert "port" in s
    assert "adapt" in s or "free" in s
