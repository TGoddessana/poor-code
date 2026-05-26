"""Path computation for project_map artifacts under .poor-code/."""
from __future__ import annotations

from pathlib import Path

from poor_code.domain.project_map import paths


def test_project_map_json(tmp_path: Path):
    assert paths.project_map_json(tmp_path) == tmp_path / "project_map.json"
