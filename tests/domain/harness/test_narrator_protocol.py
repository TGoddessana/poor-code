from poor_code.domain.harness.narrator import StepNarrator


def test_protocol_is_runtime_checkable_and_duck_typed():
    class Dummy:
        def activity(self, node, phase, state):
            return "x"
        def summary(self, node, result):
            return ("h", ())
    assert isinstance(Dummy(), StepNarrator)
