"""End-to-end build test: synthesize a small Python project and verify
the on-disk JSON shape + progress callback sequence.

UI/worker e2e is out of scope for V1 — see spec §7.4. This test exercises
the domain pipeline directly.
"""
from __future__ import annotations

import json
from pathlib import Path

from poor_code.domain.project_map import ProjectMapBuilder, ProjectMapStore
from poor_code.domain.project_map.discovery import FileDiscovery
from poor_code.domain.project_map.import_resolver import ImportResolver
from poor_code.domain.project_map.models import BuildProgress
from poor_code.domain.project_map.tests_mapping import TestsMapper


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _builder() -> ProjectMapBuilder:
    return ProjectMapBuilder(FileDiscovery(), ImportResolver(), TestsMapper())


def test_build_synthetic_project_end_to_end(tmp_path: Path):
    _write(tmp_path / ".gitignore", "__pycache__/\n")
    _write(
        tmp_path / "src/foo/__init__.py",
        "",
    )
    _write(
        tmp_path / "src/foo/bar.py",
        "import src.foo.baz\n\nclass Bar:\n    def do(self): pass\n",
    )
    _write(tmp_path / "src/foo/baz.py", "def helper(): pass\n")
    _write(tmp_path / "tests/foo/test_bar.py", "")
    _write(tmp_path / "src/broken.py", "def f(:\n")
    _write(tmp_path / "src/__pycache__/cached.py", "garbage")  # excluded by .gitignore

    progress_calls: list[BuildProgress] = []
    project_map = _builder().build(tmp_path, on_progress=progress_calls.append)

    # Discovery filtered out the cached file; the broken file appears in parse_errors.
    file_paths = {fe.path for fe in project_map.files}
    err_paths = {pe.path for pe in project_map.parse_errors}
    assert "src/foo/bar.py" in file_paths
    assert "src/foo/baz.py" in file_paths
    assert "tests/foo/test_bar.py" in file_paths
    assert "src/broken.py" in err_paths
    assert "src/__pycache__/cached.py" not in file_paths
    assert "src/__pycache__/cached.py" not in err_paths

    # Imports resolved to internal POSIX paths.
    bar = next(fe for fe in project_map.files if fe.path == "src/foo/bar.py")
    assert "src/foo/baz.py" in bar.imports

    # Tests mapping attached test file to bar.py.
    assert "tests/foo/test_bar.py" in bar.tests

    # Progress callback monotonic, final (N, N).
    counts = [bp.files_processed for bp in progress_calls]
    totals = {bp.files_total for bp in progress_calls}
    assert counts == sorted(counts) and counts[0] == 1
    assert counts[-1] == progress_calls[-1].files_total
    assert len(totals) == 1


def test_persist_and_reload_via_store(tmp_path: Path):
    _write(tmp_path / "a.py", "class A: pass\n")
    original = _builder().build(tmp_path)
    root = tmp_path / ".poor-code"
    ProjectMapStore().write(original, root)

    # JSON file exists and is well-formed.
    data = json.loads((root / "project_map.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert any(fe["path"] == "a.py" for fe in data["files"])

    # Roundtrip equals the original.
    reloaded = ProjectMapStore().read(root)
    assert reloaded == original
