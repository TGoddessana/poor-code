from poor_code.domain.harness.steering import (
    STEERING_HEADER, steering_block, steering_message,
)


def test_steering_message_none_when_empty():
    assert steering_message(()) is None


def test_steering_message_builds_user_message():
    m = steering_message(("a", "b"))
    assert m == {"role": "user", "content": f"{STEERING_HEADER}\n- a\n- b"}


def test_steering_block_empty_when_no_notes():
    assert steering_block(()) == ""


def test_steering_block_has_leading_newline_and_bullets():
    assert steering_block(("x",)) == f"\n{STEERING_HEADER}\n- x"
