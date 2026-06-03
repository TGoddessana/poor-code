from poor_code.domain.harness.nodes import explorer, implementer


def test_implementer_loop_cap_is_50():
    assert implementer.MAX_ITERATIONS == 50


def test_explorer_loop_cap_is_20():
    assert explorer.MAX_ITERATIONS == 20
