from poor_code.provider.protocols.openai_chat import _split_top_level_json


def test_single_object_returns_original_unchanged():
    assert _split_top_level_json('{"path":"a"}') == ['{"path":"a"}']


def test_concatenated_objects_split():
    out = _split_top_level_json('{"path":"a"}{"path":"b"}{"path":"c"}')
    assert out == ['{"path":"a"}', '{"path":"b"}', '{"path":"c"}']


def test_whitespace_between_objects():
    assert _split_top_level_json('{"a":1} {"b":2}') == ['{"a":1}', '{"b":2}']


def test_nested_object_not_split():
    assert _split_top_level_json('{"filter":{"a":1}}') == ['{"filter":{"a":1}}']


def test_braces_inside_strings_ignored():
    # the "}{" lives inside a string value — must NOT split
    s = '{"path":"a}{b"}'
    assert _split_top_level_json(s) == [s]


def test_escaped_quote_inside_string():
    s = '{"path":"a\\"}{\\"b"}'
    assert _split_top_level_json(s) == [s]


def test_trailing_garbage_returns_whole():
    s = '{"a":1}{"b":2}garbage'
    assert _split_top_level_json(s) == [s]


def test_truncated_returns_whole():
    s = '{"path":"a'
    assert _split_top_level_json(s) == [s]


def test_empty_returns_whole():
    assert _split_top_level_json('') == ['']
