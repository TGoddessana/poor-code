from __future__ import annotations


def compute_delta(current: str, new: str) -> str | None:
    """Suffix to append so the widget's source becomes ``new``.

    Returns the tail to append, or ``None`` if ``new`` is not an extension
    of ``current`` (caller should fall back to a full replace)."""
    if not new.startswith(current):
        return None
    return new[len(current):]
