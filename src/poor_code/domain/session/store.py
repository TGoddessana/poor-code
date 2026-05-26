"""Disk I/O for session/task artifacts. Internal — do not import outside this package."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: tmp file → os.replace.

    Guarantees that the original file at `path` (if any) is never partially overwritten:
    on any failure before os.replace, the original survives untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


class SessionStore:
    """Placeholder — methods added in subsequent tasks."""

    def __init__(self, root: Path) -> None:
        self._root = root
