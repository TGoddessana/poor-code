"""Models for the project_map domain. Frozen, slots, UTC datetimes."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.project_map.models import (
    BuildProgress,
    FileEntry,
    ParsedFile,
    ParseError,
    ProjectMap,
    RawImport,
    Symbol,
    SymbolKind,
)


def test_symbol_kind_values_are_lowercase_strings():
    assert SymbolKind.CLASS.value == "class"
    assert SymbolKind.FUNCTION.value == "function"
    assert SymbolKind.METHOD.value == "method"


def test_symbol_is_frozen_and_slotted():
    s = Symbol(name="Foo", kind=SymbolKind.CLASS, lineno=10)
    with pytest.raises(AttributeError):
        s.name = "Bar"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        s.__dict__  # slots prevents __dict__


def test_file_entry_holds_tuples_not_lists():
    fe = FileEntry(path="src/x.py", symbols=(), imports=(), tests=())
    assert isinstance(fe.symbols, tuple)
    assert isinstance(fe.imports, tuple)
    assert isinstance(fe.tests, tuple)


def test_parse_error_shape():
    pe = ParseError(path="src/broken.py", error="SyntaxError: ...")
    assert pe.path == "src/broken.py"
    assert pe.error == "SyntaxError: ..."


def test_project_map_minimal_shape():
    pm = ProjectMap(
        version=1,
        generated_at=datetime.now(UTC),
        cwd=Path("/tmp/x"),
        files=(),
        parse_errors=(),
    )
    assert pm.version == 1
    assert pm.cwd == Path("/tmp/x")
    assert pm.generated_at.tzinfo is not None


def test_raw_import_levels():
    assert RawImport(text="a.b", level=0).level == 0
    assert RawImport(text="x", level=2).level == 2
    assert RawImport(text="", level=1).text == ""


def test_parsed_file_carries_optional_parse_error():
    pf_ok = ParsedFile(path="/tmp/a.py", symbols=(), raw_imports=(), parse_error=None)
    pf_err = ParsedFile(
        path="/tmp/b.py",
        symbols=(),
        raw_imports=(),
        parse_error=ParseError(path="/tmp/b.py", error="X"),
    )
    assert pf_ok.parse_error is None
    assert pf_err.parse_error is not None


def test_build_progress_holds_counts():
    bp = BuildProgress(files_processed=3, files_total=10)
    assert bp.files_processed == 3
    assert bp.files_total == 10
