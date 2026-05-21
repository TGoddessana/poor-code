from __future__ import annotations

import json
from pathlib import Path

import pytest

from poor_code.infra.settings import Settings, SettingsLoader


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


async def test_no_files_returns_empty_effective(tmp_path):
    loader = SettingsLoader(home_dir=tmp_path / "home")
    result = await loader.load(cwd=tmp_path / "project")
    assert isinstance(result, Settings)
    assert result.effective == {}
    assert result.sources == ()


async def test_only_global(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _write(home / ".poor-code" / "settings.json", json.dumps({"a": 1}))

    loader = SettingsLoader(home_dir=home)
    result = await loader.load(cwd=project)
    assert result.effective == {"a": 1}
    assert len(result.sources) == 1
    assert result.sources[0] == home / ".poor-code" / "settings.json"


async def test_only_project(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    _write(project / ".poor-code" / "settings.json", json.dumps({"a": 1}))

    loader = SettingsLoader(home_dir=home)
    result = await loader.load(cwd=project)
    assert result.effective == {"a": 1}
    assert result.sources == (project / ".poor-code" / "settings.json",)


async def test_project_wins_on_overlap(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    _write(home / ".poor-code" / "settings.json", json.dumps({"a": 1, "b": 2}))
    _write(project / ".poor-code" / "settings.json", json.dumps({"b": 99, "c": 3}))

    loader = SettingsLoader(home_dir=home)
    result = await loader.load(cwd=project)
    assert result.effective == {"a": 1, "b": 99, "c": 3}
    assert len(result.sources) == 2


async def test_empty_file_treated_as_empty_dict(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _write(home / ".poor-code" / "settings.json", "")

    loader = SettingsLoader(home_dir=home)
    result = await loader.load(cwd=project)
    assert result.effective == {}
    assert len(result.sources) == 1


async def test_malformed_json_raises_value_error(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _write(home / ".poor-code" / "settings.json", "{not valid json")

    loader = SettingsLoader(home_dir=home)
    with pytest.raises(ValueError, match="malformed settings.json"):
        await loader.load(cwd=project)


async def test_non_object_root_raises(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _write(home / ".poor-code" / "settings.json", json.dumps([1, 2, 3]))

    loader = SettingsLoader(home_dir=home)
    with pytest.raises(ValueError, match="must be a JSON object"):
        await loader.load(cwd=project)
