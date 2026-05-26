"""ProjectMapBuilder — orchestration end-to-end."""
from __future__ import annotations

from pathlib import Path

from poor_code.domain.project_map.builder import ProjectMapBuilder
from poor_code.domain.project_map.discovery import FileDiscovery
from poor_code.domain.project_map.import_resolver import ImportResolver
from poor_code.domain.project_map.models import BuildProgress
from poor_code.domain.project_map.tests_mapping import TestsMapper


def _builder() -> ProjectMapBuilder:
    return ProjectMapBuilder(FileDiscovery(), ImportResolver(), TestsMapper())


def _write(p: Path, text: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_empty_cwd_yields_empty_map(tmp_path: Path):
    m = _builder().build(tmp_path)
    assert m.version == 1
    assert m.cwd == tmp_path
    assert m.files == ()
    assert m.parse_errors == ()


def test_normal_repo_assembles_file_entries(tmp_path: Path):
    _write(tmp_path / "src/foo.py", "class Foo:\n    def bar(self): pass\n")
    _write(tmp_path / "tests/test_foo.py", "")
    m = _builder().build(tmp_path)
    paths = {fe.path for fe in m.files}
    assert paths == {"src/foo.py", "tests/test_foo.py"}
    foo = next(fe for fe in m.files if fe.path == "src/foo.py")
    assert any(s.name == "Foo.bar" for s in foo.symbols)
    assert "tests/test_foo.py" in foo.tests


def test_syntax_error_file_goes_into_parse_errors(tmp_path: Path):
    _write(tmp_path / "src/ok.py", "def f(): pass\n")
    _write(tmp_path / "src/broken.py", "def f(:\n")
    m = _builder().build(tmp_path)
    file_paths = {fe.path for fe in m.files}
    assert "src/ok.py" in file_paths
    assert "src/broken.py" not in file_paths
    err_paths = {pe.path for pe in m.parse_errors}
    assert "src/broken.py" in err_paths


def test_on_progress_called_per_file_with_monotonic_counts(tmp_path: Path):
    _write(tmp_path / "a.py", "")
    _write(tmp_path / "b.py", "")
    _write(tmp_path / "c.py", "")
    calls: list[BuildProgress] = []
    _builder().build(tmp_path, on_progress=calls.append)
    assert [bp.files_processed for bp in calls] == [1, 2, 3]
    assert all(bp.files_total == 3 for bp in calls)


def test_on_progress_none_is_accepted(tmp_path: Path):
    _write(tmp_path / "a.py", "")
    m = _builder().build(tmp_path, on_progress=None)
    assert len(m.files) == 1


def test_files_sorted_deterministically(tmp_path: Path):
    _write(tmp_path / "z.py", "")
    _write(tmp_path / "a.py", "")
    _write(tmp_path / "m.py", "")
    m = _builder().build(tmp_path)
    assert [fe.path for fe in m.files] == ["a.py", "m.py", "z.py"]


def test_imports_resolved_to_internal_paths(tmp_path: Path):
    _write(tmp_path / "a.py", "import b\n")
    _write(tmp_path / "b.py", "")
    m = _builder().build(tmp_path)
    a = next(fe for fe in m.files if fe.path == "a.py")
    assert a.imports == ("b.py",)


def test_external_imports_dropped(tmp_path: Path):
    _write(tmp_path / "a.py", "import pathlib\nimport pytest\n")
    m = _builder().build(tmp_path)
    a = next(fe for fe in m.files if fe.path == "a.py")
    assert a.imports == ()
