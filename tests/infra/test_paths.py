from pathlib import Path

from poor_code.infra import paths


def test_config_dir(tmp_path: Path):
    assert paths.config_dir(tmp_path) == tmp_path / ".poor-code"


def test_auth_json(tmp_path: Path):
    assert paths.auth_json(tmp_path) == tmp_path / ".poor-code" / "auth.json"


def test_settings_json(tmp_path: Path):
    assert paths.settings_json(tmp_path) == tmp_path / ".poor-code" / "settings.json"


def test_poorcode_md(tmp_path: Path):
    assert paths.poorcode_md(tmp_path) == tmp_path / ".poor-code" / "POORCODE.md"


def test_system_prompt_md(tmp_path: Path):
    assert paths.system_prompt_md(tmp_path) == tmp_path / ".poor-code" / "system_prompt.md"
