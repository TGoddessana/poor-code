"""ReadCache — the harness's port of Claude Code's `readFileState`.

A session-scoped record of file reads: path -> {content, mtime, range}. The Read
tool consults it to avoid re-sending an unchanged file body (weak models routinely
re-read a file they already have in context; Claude Code's BQ telemetry measured
~18% of reads as same-file collisions). On a hit the Read tool returns a short stub
instead of the full body — the earlier read result is still in the transcript.

Correctness is anchored on mtime, NOT explicit invalidation: every read re-stats the
file, so an Edit/Write (which bumps mtime) is seen as a fresh read automatically. No
write-side bookkeeping is needed. Lives on DriverRuntime, threaded down via
ToolContext; mutated in place by the (sequentially-run) read tool, so no locking."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileState:
    content: str      # the read tool's output that was sent to the model
    mtime_ns: int     # st_mtime_ns at read time — the staleness key
    start: int        # the read range, so a different slice is not a hit
    limit: int


class ReadCache:
    """path -> FileState. Bounded by a simple FIFO cap (repos here are small; exact
    LRU would be overkill). Absent (None in ToolContext) → dedup is simply disabled,
    which is the default for direct-node unit tests."""

    def __init__(self, max_entries: int = 100) -> None:
        self._states: dict[str, FileState] = {}
        self._max = max_entries

    def get(self, key: str) -> FileState | None:
        return self._states.get(key)

    def set(self, key: str, state: FileState) -> None:
        if key not in self._states and len(self._states) >= self._max:
            self._states.pop(next(iter(self._states)))   # evict oldest (insertion order)
        self._states[key] = state

    def is_fresh_hit(self, key: str, *, mtime_ns: int, start: int, limit: int) -> bool:
        """True when this exact (range) read of an unchanged file is already cached."""
        prior = self._states.get(key)
        return (prior is not None
                and prior.mtime_ns == mtime_ns
                and prior.start == start
                and prior.limit == limit)
