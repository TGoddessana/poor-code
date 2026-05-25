from poor_code.ui.widgets.streaming_markdown import compute_delta


def test_compute_delta_prefix_match_returns_tail():
    assert compute_delta(current="Hello", new="Hello world") == " world"


def test_compute_delta_empty_current_returns_full():
    assert compute_delta(current="", new="Hello") == "Hello"


def test_compute_delta_identical_returns_empty():
    assert compute_delta(current="abc", new="abc") == ""


def test_compute_delta_non_prefix_returns_none():
    # AssistantMessageCompleted may rewrite the trailing segment with a
    # normalized final text. Signal "full replace" by returning None.
    assert compute_delta(current="Hello wrld", new="Hello world") is None
