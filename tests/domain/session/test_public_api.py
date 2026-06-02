"""Lock the public surface: only these symbols are exported from poor_code.domain.session."""


def test_public_imports():
    from poor_code.domain.session import (
        WorkItemPolicies,
        Session,
        SessionService,
        SessionState,
        SessionStatus,
        WorkItem,
        WorkItemState,
        WorkItemStatus,
    )

    # Touch each to keep linters honest.
    assert SessionService is not None
    assert SessionStatus.READY.value == "ready"
    assert WorkItemStatus.PENDING.value == "pending"
    assert WorkItemPolicies().implementation_locked is True
    assert Session is not None
    assert SessionState is not None
    assert WorkItem is not None
    assert WorkItemState is not None


def test_public_surface_locked_to_all():
    """__all__ defines the contract. Internal classes like SessionStore must not appear."""
    import poor_code.domain.session as session_pkg

    expected = {
        "WorkItemPolicies",
        "Session",
        "SessionService",
        "SessionState",
        "SessionStatus",
        "WorkItem",
        "WorkItemState",
        "WorkItemStatus",
    }
    assert set(session_pkg.__all__) == expected

    # SessionStore is internal — must not appear on the package root.
    assert not hasattr(session_pkg, "SessionStore"), (
        "SessionStore is internal — downstream code must go through SessionService"
    )
