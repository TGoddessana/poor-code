"""Path computation for project_map artifacts. Internal — do not import outside this package."""
from __future__ import annotations

from pathlib import Path


def project_map_json(root: Path) -> Path:
    return root / "project_map.json"
