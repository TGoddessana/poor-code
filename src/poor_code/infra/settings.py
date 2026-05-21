"""SettingsLoader — merges ~/.poor-code/settings.json with ./.poor-code/settings.json.

Project overrides global at the top-level key (1-depth shallow merge). Nested dicts
are replaced wholesale in V1. Missing files are normal (effective = {}); malformed
JSON raises ValueError with a human-readable path; PermissionError bubbles.
"""
from __future__ import annotations

import json
import types
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    sources: tuple[Path, ...]
    effective: Mapping[str, Any]


class SettingsLoader:
    def __init__(self, home_dir: Path | None = None) -> None:
        self._home = home_dir if home_dir is not None else Path.home()

    async def load(self, cwd: Path) -> Settings:
        sources: list[Path] = []
        merged: dict[str, Any] = {}

        for path in (
            self._home / ".poor-code" / "settings.json",
            cwd / ".poor-code" / "settings.json",
        ):
            data = _load_one(path)
            if data is None:
                continue
            sources.append(path)
            merged.update(data)

        return Settings(sources=tuple(sources), effective=types.MappingProxyType(merged))


def _load_one(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed settings.json at {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(
            f"settings.json at {path} must be a JSON object, got {type(data).__name__}"
        )
    return data
