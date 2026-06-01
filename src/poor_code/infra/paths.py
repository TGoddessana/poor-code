"""Filesystem layout for poor-code's ``.poor-code/`` config directories.

Single source of truth for the directory name and the well-known files inside it,
so global config (auth, settings, prompts) never drifts apart again. ``base`` is the
home directory for global config or ``cwd`` for project-local config.
"""
from __future__ import annotations

from pathlib import Path

DIRNAME = ".poor-code"


def config_dir(base: Path) -> Path:
    return base / DIRNAME


def auth_json(home: Path) -> Path:
    return config_dir(home) / "auth.json"


def settings_json(base: Path) -> Path:
    return config_dir(base) / "settings.json"


def poorcode_md(base: Path) -> Path:
    return config_dir(base) / "POORCODE.md"


def system_prompt_md(base: Path) -> Path:
    return config_dir(base) / "system_prompt.md"
