from poor_code.domain.session.models import Policy, SessionState


def test_policy_default_is_supervised():
    assert SessionState().policy is Policy.SUPERVISED


def test_with_policy_sets_field_immutably():
    st = SessionState()
    st2 = st.with_policy(Policy.FULL_AUTO)
    assert st2.policy is Policy.FULL_AUTO
    assert st.policy is Policy.SUPERVISED


def test_policy_has_three_members():
    assert {p.value for p in Policy} == {"supervised", "full_auto", "paranoid"}
