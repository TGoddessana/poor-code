"""Python AST parser — symbols + imports + error handling."""
from __future__ import annotations

from pathlib import Path

from poor_code.domain.project_map import parsers
from poor_code.domain.project_map.models import RawImport, SymbolKind


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_top_level_class_function_and_async_function(tmp_path: Path):
    f = _write(tmp_path / "a.py", "class Foo:\n    pass\n\ndef helper():\n    pass\n\nasync def aio():\n    pass\n")
    pf = parsers.parse_file(f)
    assert pf.parse_error is None
    names = {(s.name, s.kind) for s in pf.symbols}
    assert ("Foo", SymbolKind.CLASS) in names
    assert ("helper", SymbolKind.FUNCTION) in names
    assert ("aio", SymbolKind.FUNCTION) in names


def test_class_methods_get_dotted_names(tmp_path: Path):
    f = _write(tmp_path / "a.py", "class Foo:\n    def bar(self): pass\n    async def baz(self): pass\n")
    pf = parsers.parse_file(f)
    names = {(s.name, s.kind) for s in pf.symbols}
    assert ("Foo", SymbolKind.CLASS) in names
    assert ("Foo.bar", SymbolKind.METHOD) in names
    assert ("Foo.baz", SymbolKind.METHOD) in names


def test_nested_classes_and_nested_functions_excluded(tmp_path: Path):
    src = (
        "class Outer:\n"
        "    class Inner: pass\n"
        "    def m(self):\n"
        "        def inner_fn(): pass\n"
        "\n"
        "def top():\n"
        "    def nested(): pass\n"
    )
    f = _write(tmp_path / "a.py", src)
    pf = parsers.parse_file(f)
    names = {s.name for s in pf.symbols}
    assert names == {"Outer", "Outer.m", "top"}


def test_module_level_imports_extracted(tmp_path: Path):
    src = (
        "import a.b\n"
        "from c.d import e\n"
        "from . import x\n"
        "from .x.y import z\n"
        "from ..pkg import w\n"
    )
    f = _write(tmp_path / "a.py", src)
    pf = parsers.parse_file(f)
    assert RawImport(text="a.b", level=0) in pf.raw_imports
    assert RawImport(text="c.d", level=0) in pf.raw_imports
    assert RawImport(text="", level=1) in pf.raw_imports
    assert RawImport(text="x.y", level=1) in pf.raw_imports
    assert RawImport(text="pkg", level=2) in pf.raw_imports


def test_in_function_imports_ignored(tmp_path: Path):
    src = "import top_level\n\ndef f():\n    import inner\n"
    f = _write(tmp_path / "a.py", src)
    pf = parsers.parse_file(f)
    assert RawImport(text="top_level", level=0) in pf.raw_imports
    assert all(ri.text != "inner" for ri in pf.raw_imports)


def test_syntax_error_returns_parse_error(tmp_path: Path):
    f = _write(tmp_path / "broken.py", "def f(:\n")
    pf = parsers.parse_file(f)
    assert pf.parse_error is not None
    assert "SyntaxError" in pf.parse_error.error
    assert pf.symbols == ()
    assert pf.raw_imports == ()


def test_unicode_decode_error_returns_parse_error(tmp_path: Path):
    f = tmp_path / "bad.py"
    f.write_bytes(b"\xff\xfeinvalid utf-8")
    pf = parsers.parse_file(f)
    assert pf.parse_error is not None
    assert "UnicodeDecodeError" in pf.parse_error.error


def test_empty_file_parses_to_empty_symbols_no_error(tmp_path: Path):
    f = _write(tmp_path / "a.py", "")
    pf = parsers.parse_file(f)
    assert pf.parse_error is None
    assert pf.symbols == ()
    assert pf.raw_imports == ()


def test_unsupported_extension_returns_parse_error(tmp_path: Path):
    f = _write(tmp_path / "a.js", "function x() {}")
    pf = parsers.parse_file(f)
    assert pf.parse_error is not None
    assert "unsupported extension" in pf.parse_error.error
