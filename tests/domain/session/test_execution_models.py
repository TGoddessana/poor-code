from poor_code.domain.session.models import Phase


def test_phase_has_execution_values():
    assert Phase.IMPLEMENTING.value == "implementing"
    assert Phase.FINALIZING.value == "finalizing"
