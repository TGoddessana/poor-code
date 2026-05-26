"""Lock the public surface: only these symbols are exported from poor_code.domain.session."""


def test_public_imports():
    from poor_code.domain.session import (
        Policies,
        Session,
        SessionService,
        SessionState,
        SessionStatus,
        Task,
        TaskState,
        TaskStatus,
    )

    # Touch each to keep linters honest.
    assert SessionService is not None
    assert SessionStatus.READY.value == "ready"
    assert TaskStatus.PENDING.value == "pending"
    assert Policies().implementation_locked is True
    assert Session is not None
    assert SessionState is not None
    assert Task is not None
    assert TaskState is not None


def test_public_surface_locked_to_all():
    """__all__ defines the contract. Internal classes like SessionStore must not appear."""
    import poor_code.domain.session as session_pkg

    expected = {
        "Policies",
        "Session",
        "SessionService",
        "SessionState",
        "SessionStatus",
        "Task",
        "TaskState",
        "TaskStatus",
    }
    assert set(session_pkg.__all__) == expected

    # SessionStore is internal — must not appear on the package root.
    assert not hasattr(session_pkg, "SessionStore"), (
        "SessionStore is internal — downstream code must go through SessionService"
    )
