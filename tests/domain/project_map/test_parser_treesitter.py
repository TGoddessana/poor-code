from pathlib import Path
from poor_code.domain.project_map import parsers
from poor_code.domain.project_map.models import SymbolKind

def _w(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p

def test_python_symbols_methods_dotted(tmp_path):
    f = _w(tmp_path / "a.py",
           'class Foo:\n'
           '    def bar(self, x: int) -> None:\n'
           '        """Do bar."""\n'
           '        helper()\n'
           '\n'
           'def helper():\n'
           '    pass\n')
    pf = parsers.parse_file(f)
    assert pf.parse_error is None
    assert pf.language == "python"
    assert pf.content_hash.startswith("sha256:")
    by_name = {s.name: s for s in pf.symbols}
    assert by_name["Foo"].kind == SymbolKind.CLASS
    assert by_name["Foo.bar"].kind == SymbolKind.METHOD
    assert by_name["helper"].kind == SymbolKind.FUNCTION
    assert by_name["Foo.bar"].signature == "(self, x: int) -> None"
    assert by_name["Foo.bar"].doc == "Do bar."

def test_python_raw_calls_have_enclosing_caller(tmp_path):
    f = _w(tmp_path / "a.py",
           'class Foo:\n'
           '    def bar(self):\n'
           '        helper()\n'
           'def helper():\n'
           '    other()\n')
    pf = parsers.parse_file(f)
    pairs = {(rc.caller, rc.callee) for rc in pf.raw_calls}
    assert ("Foo.bar", "helper") in pairs
    assert ("helper", "other") in pairs

def test_python_imports_with_levels(tmp_path):
    f = _w(tmp_path / "a.py",
           "import sys\n"
           "from a.b import c\n"
           "from . import x\n"
           "from ..pkg import y\n")
    pf = parsers.parse_file(f)
    texts = {(ri.text, ri.level) for ri in pf.raw_imports}
    assert ("sys", 0) in texts
    assert ("a.b", 0) in texts
    assert ("", 1) in texts        # from . import x
    assert ("pkg", 2) in texts     # from ..pkg import y

def test_typescript_basic(tmp_path):
    f = _w(tmp_path / "a.ts",
           "export class Svc {\n"
           "  run(x: number): void { helper(); }\n"
           "}\n"
           "function helper() {}\n")
    pf = parsers.parse_file(f)
    assert pf.parse_error is None
    assert pf.language == "typescript"
    names = {s.name for s in pf.symbols}
    assert "Svc" in names
    assert any(n.endswith("run") for n in names)
    assert "helper" in names

def test_syntax_error_to_parse_error(tmp_path):
    # tree-sitter is error-tolerant; we flag files whose tree has errors.
    f = _w(tmp_path / "broken.py", "def f(:\n")
    pf = parsers.parse_file(f)
    assert pf.parse_error is not None
    assert pf.symbols == () and pf.raw_imports == ()

def test_oserror_unreadable(tmp_path):
    pf = parsers.parse_file(tmp_path / "does_not_exist.py")
    assert pf.parse_error is not None

def test_unsupported_language_is_parse_error(tmp_path):
    f = _w(tmp_path / "a.rs", "fn main() {}")
    pf = parsers.parse_file(f)
    assert pf.parse_error is not None
