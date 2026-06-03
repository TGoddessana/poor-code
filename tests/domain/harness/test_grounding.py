from poor_code.domain.harness.grounding import is_prose, validation_floor_hint


def test_empty_is_rejected():
    assert validation_floor_hint("   ") is not None


def test_prose_is_rejected():
    assert is_prose("Check that the file exists")
    assert validation_floor_hint("Verify the server responds") is not None


def test_real_command_passes():
    assert not is_prose("pytest tests/test_x.py")
    assert validation_floor_hint("printf '%s' \"$E\" | diff - hello.txt") is None


def test_wc_command_is_not_blocklisted():
    # task-independent floor must NOT ban byte-count commands (over-fit guard)
    assert validation_floor_hint("[ \"$(wc -c < f)\" = \"42\" ]") is None
