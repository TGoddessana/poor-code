from poor_code.ui.screens.state_inspector import pick_context_source


class _App:
    def __init__(self, live=None, parked=None):
        self._live_state = live
        self._harness_state = parked


def test_prefers_live_over_parked():
    assert pick_context_source(_App(live="LIVE", parked="PARKED")) == "LIVE"


def test_falls_back_to_parked():
    assert pick_context_source(_App(live=None, parked="PARKED")) == "PARKED"


def test_none_when_neither():
    assert pick_context_source(_App()) is None
