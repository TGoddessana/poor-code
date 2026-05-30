"""Language dispatch for project_map. Internal — do not import outside this package.

Extension first; shebang fallback for extension-less files. Only languages present
in EXTENSION_TO_LANGUAGE (or resolvable via shebang) are admitted; everything else
returns None and is skipped by discovery.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
}

SHEBANG_INTERPRETER_TO_LANGUAGE: dict[str, str] = {
    "python": "python", "python3": "python",
    "node": "javascript", "nodejs": "javascript",
}

TIER: dict[str, Literal["first", "second"]] = {
    "python": "first", "javascript": "first", "typescript": "first",
}


def detect_language(path: Path) -> str | None:
    lang = EXTENSION_TO_LANGUAGE.get(path.suffix)
    if lang is not None:
        return lang
    if path.suffix:
        return None
    return _detect_via_shebang(path)


def _detect_via_shebang(path: Path) -> str | None:
    try:
        with path.open("rb") as fh:
            head = fh.read(256)
    except OSError:
        return None
    if not head.startswith(b"#!"):
        return None
    first_line = head.split(b"\n", 1)[0].decode("utf-8", "replace")
    for token in reversed(first_line.replace("#!", "").split()):
        name = token.rsplit("/", 1)[-1]
        if name in SHEBANG_INTERPRETER_TO_LANGUAGE:
            return SHEBANG_INTERPRETER_TO_LANGUAGE[name]
    return None
