from __future__ import annotations

from pathlib import Path

from poor_code.infra.settings import Settings
from poor_code.infra.system_prompt import (
    DYNAMIC_BOUNDARY,
    SystemPrompt,
    SystemPromptComposer,
)


def _empty_settings() -> Settings:
    return Settings(sources=(), effective={})


def test_built_in_has_static_then_boundary_then_dynamic(tmp_path):
    composer = SystemPromptComposer(home_dir=tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()

    result = composer.compose(_empty_settings(), cwd=project)

    assert isinstance(result, SystemPrompt)
    assert "poor-code" in result.text.lower()
    assert DYNAMIC_BOUNDARY in result.text
    static_idx = result.text.index(result.static)
    boundary_idx = result.text.index(DYNAMIC_BOUNDARY)
    dynamic_idx = result.text.index(result.dynamic)
    assert static_idx < boundary_idx < dynamic_idx


def test_dynamic_includes_cwd_and_platform(tmp_path):
    composer = SystemPromptComposer(home_dir=tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()

    result = composer.compose(_empty_settings(), cwd=project)

    assert str(project) in result.dynamic
    assert any(p in result.dynamic.lower() for p in ("darwin", "linux", "windows"))


def test_global_appendix_appears_after_dynamic(tmp_path):
    home = tmp_path / "home"
    (home / ".poor-code").mkdir(parents=True)
    (home / ".poor-code" / "system_prompt.md").write_text("USER GLOBAL ADDITION")
    project = tmp_path / "project"
    project.mkdir()

    composer = SystemPromptComposer(home_dir=home)
    result = composer.compose(_empty_settings(), cwd=project)

    assert "USER GLOBAL ADDITION" in result.text
    assert result.text.index(DYNAMIC_BOUNDARY) < result.text.index("USER GLOBAL ADDITION")


def test_project_appendix_appears_after_global(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".poor-code").mkdir(parents=True)
    (project / ".poor-code").mkdir(parents=True)
    (home / ".poor-code" / "system_prompt.md").write_text("GLOBAL_X")
    (project / ".poor-code" / "system_prompt.md").write_text("PROJECT_Y")

    composer = SystemPromptComposer(home_dir=home)
    result = composer.compose(_empty_settings(), cwd=project)

    assert result.text.index("GLOBAL_X") < result.text.index("PROJECT_Y")


def test_empty_appendix_file_skipped(tmp_path):
    home = tmp_path / "home"
    (home / ".poor-code").mkdir(parents=True)
    (home / ".poor-code" / "system_prompt.md").write_text("   \n  ")
    project = tmp_path / "project"
    project.mkdir()

    composer = SystemPromptComposer(home_dir=home)
    result = composer.compose(_empty_settings(), cwd=project)
    assert "   " not in result.text
