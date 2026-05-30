"""End-to-end build test: synthesize a small multi-language project and verify
the graph shape, the on-disk JSON shape + progress callback sequence, plus a
regression guard that builds poor-code on itself (the V1 src-layout blocker).

UI/worker e2e is out of scope here — see spec §7.4. These tests exercise the
v2 domain pipeline directly via the public surface.
"""
from __future__ import annotations

import json
from pathlib import Path

from poor_code.domain.project_map import (
    ProjectMapStore,
    make_default_builder,
)
from poor_code.domain.project_map.models import BuildProgress


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


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
    # A TypeScript pair exercises the multi-language path + relative-spec resolver.
    _write(tmp_path / "web/util.ts", "export const x = 1;\n")
    _write(tmp_path / "web/app.ts", "import { x } from './util';\nexport const y = x;\n")
    _write(tmp_path / "src/broken.py", "def f(:\n")
    _write(tmp_path / "src/__pycache__/cached.py", "garbage")  # excluded by .gitignore

    progress_calls: list[BuildProgress] = []
    project_map = make_default_builder().build(tmp_path, on_progress=progress_calls.append)

    # v2 schema.
    assert project_map.version == 2

    # Discovery filtered out the cached file; the broken file appears in parse_errors.
    file_paths = {fe.path for fe in project_map.files}
    err_paths = {pe.path for pe in project_map.parse_errors}
    assert "src/foo/bar.py" in file_paths
    assert "src/foo/baz.py" in file_paths
    assert "tests/foo/test_bar.py" in file_paths
    assert "web/util.ts" in file_paths
    assert "web/app.ts" in file_paths
    assert "src/broken.py" in err_paths
    assert "src/__pycache__/cached.py" not in file_paths
    assert "src/__pycache__/cached.py" not in err_paths

    # Multi-language: each file carries a resolved language tag.
    by_path = {fe.path: fe for fe in project_map.files}
    assert by_path["src/foo/bar.py"].language == "python"
    assert by_path["web/app.ts"].language == "typescript"
    languages = {fe.language for fe in project_map.files}
    assert {"python", "typescript"} <= languages

    # Python imports resolve to internal POSIX paths (src-layout aware).
    bar = by_path["src/foo/bar.py"]
    assert "src/foo/baz.py" in bar.imports
    # Reverse edge is populated.
    assert "src/foo/bar.py" in by_path["src/foo/baz.py"].imported_by

    # TS relative import resolves './util' -> web/util.ts.
    assert "web/util.ts" in by_path["web/app.ts"].imports
    assert "web/app.ts" in by_path["web/util.ts"].imported_by

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
    original = make_default_builder().build(tmp_path)
    root = tmp_path / ".poor-code"
    ProjectMapStore().write(original, root)

    # JSON file exists and is well-formed.
    data = json.loads((root / "project_map.json").read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert any(fe["path"] == "a.py" for fe in data["files"])

    # Roundtrip equals the original.
    reloaded = ProjectMapStore().read(root)
    assert reloaded == original


def test_self_build_import_coverage_far_above_v1(tmp_path):
    """Building poor-code on itself must resolve internal imports (V1 was ~4%)."""
    from pathlib import Path
    from poor_code.domain.project_map import make_default_builder
    repo = Path(__file__).resolve().parents[2]  # project root
    src = repo / "src"
    m = make_default_builder().build(src)
    py = [fe for fe in m.files if fe.language == "python"]
    with_imports = [fe for fe in py if fe.imports]
    # V1 produced ~4%; src-layout fix should clear 30% easily on this codebase.
    assert len(py) > 20
    assert len(with_imports) / len(py) > 0.30
    # a known hub: app.py imports several internal modules
    app = next((fe for fe in m.files if fe.path.endswith("poor_code/app.py")), None)
    assert app is not None and len(app.imports) >= 3
