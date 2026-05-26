"""ImportResolver — RawImport → internal cwd-relative POSIX paths."""
from __future__ import annotations

from poor_code.domain.project_map.import_resolver import ImportResolver
from poor_code.domain.project_map.models import ParsedFile, RawImport


def _pf(path: str, *imports: RawImport) -> ParsedFile:
    return ParsedFile(path=path, symbols=(), raw_imports=imports, parse_error=None)


def test_absolute_import_resolves_to_module_file():
    files = (
        _pf("a/b/c.py"),
        _pf("caller.py", RawImport(text="a.b.c", level=0)),
    )
    out = ImportResolver().resolve(files)
    assert out["caller.py"] == ("a/b/c.py",)


def test_absolute_import_resolves_to_init_when_no_module_file():
    files = (
        _pf("a/b/__init__.py"),
        _pf("caller.py", RawImport(text="a.b", level=0)),
    )
    out = ImportResolver().resolve(files)
    assert out["caller.py"] == ("a/b/__init__.py",)


def test_module_file_preferred_over_init():
    # When both a/b.py and a/b/__init__.py exist, the .py file wins.
    files = (
        _pf("a/b.py"),
        _pf("a/b/__init__.py"),
        _pf("caller.py", RawImport(text="a.b", level=0)),
    )
    out = ImportResolver().resolve(files)
    assert out["caller.py"] == ("a/b.py",)


def test_relative_level_1_resolves_within_same_package():
    files = (
        _pf("pkg/sub/x.py"),
        _pf("pkg/sub/foo.py", RawImport(text="x", level=1)),
    )
    out = ImportResolver().resolve(files)
    assert out["pkg/sub/foo.py"] == ("pkg/sub/x.py",)


def test_relative_level_2_ascends_one_package():
    files = (
        _pf("pkg/other.py"),
        _pf("pkg/sub/foo.py", RawImport(text="other", level=2)),
    )
    out = ImportResolver().resolve(files)
    assert out["pkg/sub/foo.py"] == ("pkg/other.py",)


def test_relative_empty_text_resolves_to_package_init():
    files = (
        _pf("pkg/sub/__init__.py"),
        _pf("pkg/sub/foo.py", RawImport(text="", level=1)),
    )
    out = ImportResolver().resolve(files)
    assert out["pkg/sub/foo.py"] == ("pkg/sub/__init__.py",)


def test_external_imports_are_dropped():
    files = (
        _pf("caller.py", RawImport(text="pathlib", level=0), RawImport(text="pytest", level=0)),
    )
    out = ImportResolver().resolve(files)
    assert out.get("caller.py", ()) == ()


def test_self_import_dropped():
    files = (
        _pf("a.py", RawImport(text="a", level=0)),
    )
    out = ImportResolver().resolve(files)
    assert out.get("a.py", ()) == ()


def test_dedup_preserves_first_occurrence_order():
    files = (
        _pf("a.py"),
        _pf("b.py"),
        _pf("caller.py",
            RawImport(text="b", level=0),
            RawImport(text="a", level=0),
            RawImport(text="b", level=0),
        ),
    )
    out = ImportResolver().resolve(files)
    assert out["caller.py"] == ("b.py", "a.py")


def test_files_with_no_imports_get_no_entry():
    files = (_pf("a.py"),)
    out = ImportResolver().resolve(files)
    assert out.get("a.py", ()) == ()
