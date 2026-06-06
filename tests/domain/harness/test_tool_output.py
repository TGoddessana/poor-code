"""FM4: bound the tool output re-sent to the model every round. The implementer
re-sends the whole accumulating message list each round, so a single 253KB `od -An -c`
dump becomes O(rounds) bloat — and context bloat hurts weak models disproportionately
(ACON). This is the cheapest, deterministic compaction: cap size (head+tail) and elide
genuinely binary/non-text dumps. The sink still shows the full output; only the
re-sent LLM payload is clamped."""
from poor_code.domain.harness.tool_output import (
    MAX_TOOL_RESULT_CHARS, clamp_tool_output,
)


def test_short_output_is_untouched():
    out = "exit 0\nall good"
    assert clamp_tool_output(out) == out


def test_large_text_output_is_head_tail_clamped():
    out = "A" * 50_000 + "ZEND"
    clamped = clamp_tool_output(out)
    assert len(clamped) < len(out)
    assert len(clamped) <= MAX_TOOL_RESULT_CHARS + 200  # + the elision marker
    assert clamped.startswith("A")           # head kept
    assert clamped.rstrip().endswith("ZEND")  # tail kept (errors/tracebacks live there)
    assert "elided" in clamped


def test_binary_dump_is_elided_to_head_only():
    # genuine binary content (NUL bytes / control chars) -> keep head, drop the rest
    out = "\x00\x01\x02\x03" * 5000
    clamped = clamp_tool_output(out)
    assert "elided" in clamped
    assert len(clamped) < 2000


def test_non_utf8_replacement_chars_treated_as_binary():
    out = "�" * 10_000
    clamped = clamp_tool_output(out)
    assert "elided" in clamped
    assert len(clamped) < 2000


def test_normal_log_with_some_newlines_not_flagged_binary():
    out = "line\n" * 100  # plenty of newlines, all printable
    assert clamp_tool_output(out) == out
