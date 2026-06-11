"""Deterministic tool-result compaction (FM4).

The implementer/explorer re-send their whole growing message list to the model every
round, so an unbounded tool result (a 253KB hexdump, a binary file body) inflates the
context O(rounds). Context bloat is disproportionately harmful to weak models (ACON),
so this is an accuracy lever, not just a cost one. The cheapest fix is deterministic:
cap the size (keep head AND tail — tracebacks/exit lines live at the tail) and elide
genuinely binary/non-text dumps to the head only. No LLM call, no provider change."""
from __future__ import annotations

_HEAD = 1200
_TAIL = 800
MAX_TOOL_RESULT_CHARS = _HEAD + _TAIL


def _looks_binary(s: str) -> bool:
    """Heuristic: a NUL byte, or a high density of control / UTF-8-replacement chars
    in the leading sample, means the body is binary noise (keep only the head)."""
    sample = s[:4096]
    if not sample:
        return False
    if "\x00" in sample:
        return True
    noise = sum(1 for c in sample if ord(c) < 32 and c not in "\t\n\r")
    noise += sample.count("�")  # non-UTF8 decode replacement char
    return noise / len(sample) > 0.10


def clamp_tool_output(output: str, *, head: int = _HEAD, tail: int = _TAIL) -> str:
    """Return a re-send-safe version of a tool result: full text when small, a
    head+tail slice when large, head-only when it looks binary. head/tail override
    the default budget (callers in validation paths give the tail a bigger share so
    pytest tracebacks survive)."""
    if _looks_binary(output):
        return f"{output[:head]}\n[binary/non-text output elided: {len(output)} chars]"
    if len(output) <= head + tail:
        return output
    elided = len(output) - head - tail
    return f"{output[:head]}\n…[{elided} chars elided]…\n{output[-tail:]}"
