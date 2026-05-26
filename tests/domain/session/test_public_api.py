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


def test_internal_modules_not_part_of_public_surface():
    """store and paths must not be re-exported from the package root."""
    import poor_code.domain.session as session_pkg

    assert not hasattr(session_pkg, "SessionStore"), (
        "SessionStore is internal — downstream code must go through SessionService"
    )
    assert not hasattr(session_pkg, "paths"), (
        "paths module is internal — downstream code must use SessionService.task_dir"
    )
