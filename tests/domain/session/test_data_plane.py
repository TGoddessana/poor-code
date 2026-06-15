import pytest
from poor_code.domain.session.models import SessionState, MissingInput


class _Widget:
    def __init__(self, n: int) -> None:
        self.n = n


def test_put_then_require_returns_artifact():
    w = _Widget(5)
    st = SessionState().put(w)
    assert st.require(_Widget) is w
    assert st.require(_Widget).n == 5


def test_put_is_immutable():
    base = SessionState()
    st = base.put(_Widget(1))
    assert base._data == {}
    assert _Widget in st._data


def test_require_missing_custom_type_raises():
    with pytest.raises(MissingInput):
        SessionState().require(_Widget)


def test_data_default_is_empty_and_states_equal():
    assert SessionState() == SessionState()
    assert SessionState()._data == {}


def test_data_participates_in_equality():
    a = SessionState()
    b = SessionState().put(_Widget(1))
    assert a != b
