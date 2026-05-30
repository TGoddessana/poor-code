from pathlib import Path
from poor_code.domain.project_map.builder import ProjectMapBuilder
from poor_code.domain.project_map.discovery import FileDiscovery
from poor_code.domain.project_map.import_resolver import ImportResolver
from poor_code.domain.project_map.call_resolver import CallResolver
from poor_code.domain.project_map.tests_mapping import TestsMapper
from poor_code.domain.project_map.models import BuildProgress

def _builder():
    return ProjectMapBuilder(FileDiscovery(), ImportResolver(), CallResolver(), TestsMapper())

def _w(p: Path, t: str = ""):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t, encoding="utf-8"); return p

def test_empty_cwd(tmp_path):
    m = _builder().build(tmp_path)
    assert m.version == 2 and m.files == () and m.parse_errors == ()

def test_assembles_v2_entry_with_graph(tmp_path):
    _w(tmp_path / "src/pkg/__init__.py", "")
    _w(tmp_path / "src/pkg/app.py",
       "from pkg import a\n"
       "class App:\n"
       "    def run(self):\n"
       "        helper()\n"
       "def helper():\n    pass\n")
    _w(tmp_path / "src/pkg/a.py", "def helper():\n    pass\n")
    m = _builder().build(tmp_path)
    app = next(fe for fe in m.files if fe.path == "src/pkg/app.py")
    assert app.language == "python"
    assert app.content_hash.startswith("sha256:")
    assert "src/pkg/__init__.py" in app.imports                # src-layout resolved (from pkg import a -> package)
    pkg_init = next(fe for fe in m.files if fe.path == "src/pkg/__init__.py")
    assert "src/pkg/app.py" in pkg_init.imported_by            # reverse edge
    run = next(s for s in app.symbols if s.name == "App.run")
    assert run.calls                                           # call captured (best-effort)

def test_incremental_skips_unchanged_parse(tmp_path, monkeypatch):
    _w(tmp_path / "a.py", "def f():\n    pass\n")
    b = _builder()
    m1 = b.build(tmp_path)
    # second build with previous parsed list as cache: parser must NOT be called for unchanged file
    import poor_code.domain.project_map.parsers as parsers_mod
    calls = {"n": 0}
    real = parsers_mod.parse_file
    def spy(p):
        calls["n"] += 1
        return real(p)
    monkeypatch.setattr(parsers_mod, "parse_file", spy)
    m2 = b.build(tmp_path, previous_parsed=b._last_parsed)
    assert calls["n"] == 0
    assert {fe.path for fe in m2.files} == {fe.path for fe in m1.files}

def test_incremental_reparses_changed(tmp_path, monkeypatch):
    f = _w(tmp_path / "a.py", "def f():\n    pass\n")
    b = _builder()
    m1 = b.build(tmp_path)
    prev = b._last_parsed
    f.write_text("def f():\n    pass\ndef g():\n    pass\n", encoding="utf-8")
    import poor_code.domain.project_map.parsers as parsers_mod
    calls = {"n": 0}
    real = parsers_mod.parse_file
    monkeypatch.setattr(parsers_mod, "parse_file", lambda p: (calls.__setitem__("n", calls["n"]+1) or real(p)))
    m2 = b.build(tmp_path, previous_parsed=prev)
    assert calls["n"] == 1

def test_parse_error_into_errors(tmp_path):
    _w(tmp_path / "ok.py", "def f():\n    pass\n")
    _w(tmp_path / "bad.py", "def f(:\n")
    m = _builder().build(tmp_path)
    assert "bad.py" in {pe.path for pe in m.parse_errors}
    assert "bad.py" not in {fe.path for fe in m.files}

def test_progress_monotonic(tmp_path):
    for n in "abc":
        _w(tmp_path / f"{n}.py", "")
    seen = []
    _builder().build(tmp_path, on_progress=seen.append)
    assert [bp.files_processed for bp in seen] == [1, 2, 3]
    assert all(isinstance(bp, BuildProgress) and bp.files_total == 3 for bp in seen)
