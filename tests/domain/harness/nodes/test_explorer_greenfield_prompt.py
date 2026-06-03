"""The explore-loop prompt must give a greenfield stop-condition. Without one,
the 'keep searching until you confirm the code' instruction becomes an infinite
loop on an empty repo (no code exists to confirm), and a compliant model widens
the search until it escapes cwd. See bench finding 2026-06-04."""
from poor_code.domain.harness.nodes.explorer import _EXPLORE_SYSTEM


def test_explore_prompt_has_greenfield_stop_condition():
    s = _EXPLORE_SYSTEM.lower()
    assert "greenfield" in s
    # it must tell the model to stop (not widen) when there is no existing code
    assert "stop" in s


def test_explore_prompt_points_at_structured_browsing_tools():
    s = _EXPLORE_SYSTEM.lower()
    assert "list" in s and "glob" in s
