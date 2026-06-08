"""TraceSink — append-only JSONL of the per-turn observability stream.

A durable mirror of the coarse node-lifecycle events so a turn's "what happened
and why it ended" survives the terminal closing. Imports only stdlib (domain rule).
One file per turn at sessions/<sid>/turns/<tid>/trace.jsonl."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TraceSink:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._ensured = False

    def _ensure(self) -> None:
        if not self._ensured:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._ensured = True

    def write(self, record: dict[str, Any]) -> None:
        self._ensure()
        rec = dict(record)
        rec.setdefault("ts", datetime.now(UTC).isoformat())
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
