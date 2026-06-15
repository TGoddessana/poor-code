import pytest
from poor_code.domain.session.models import (
    SessionState, MissingInput, Request, RequestKind, Plan, Requirement,
)


def test_require_returns_present_value():
    req = Request(raw_text="hi", kind=RequestKind.ENGINEERING)
    st = SessionState().with_request(req)
    assert st.require(Request) is req


def test_require_typed_value_roundtrip_requirement():
    r = Requirement(summary="do x")
    st = SessionState().with_requirement(r)
    assert st.require(Requirement).summary == "do x"


def test_require_missing_raises_with_helpful_message():
    st = SessionState()
    with pytest.raises(MissingInput) as ei:
        st.require(Plan)
    assert "Plan" in str(ei.value)
    assert ei.value.required_type is Plan


def test_require_unknown_type_raises_missing_input():
    class Foo:
        ...
    with pytest.raises(MissingInput):
        SessionState().require(Foo)
