"""Models for the project_map domain. Frozen, slots, UTC datetimes."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import pytest
from poor_code.domain.project_map.models import (
    BuildProgress, FileEntry, ParseError, ParsedFile, ProjectMap,
    RawCall, RawImport, Symbol, SymbolKind,
)


def test_symbol_kind_values():
    assert SymbolKind.CLASS.value == "class"
    assert SymbolKind.FUNCTION.value == "function"
    assert SymbolKind.METHOD.value == "method"

def test_symbol_v2_fields():
    s = Symbol(name="Foo.bar", kind=SymbolKind.METHOD, lineno=2,
               signature="(self, x: int) -> None", doc="Do bar.",
               calls=("Foo.helper",), called_by=("Caller.run",))
    assert s.signature == "(self, x: int) -> None"
    assert s.doc == "Do bar."
    assert s.calls == ("Foo.helper",)
    assert s.called_by == ("Caller.run",)
    with pytest.raises(AttributeError):
        s.name = "x"  # frozen

def test_symbol_optionals_default_none_and_empty():
    s = Symbol(name="f", kind=SymbolKind.FUNCTION, lineno=1,
               signature=None, doc=None, calls=(), called_by=())
    assert s.signature is None and s.doc is None
    assert s.calls == () and s.called_by == ()

def test_file_entry_v2_fields():
    fe = FileEntry(path="src/x.py", language="python", content_hash="sha256:abc",
                   symbols=(), imports=(), imported_by=(), tests=())
    assert fe.language == "python"
    assert fe.content_hash == "sha256:abc"
    assert fe.imported_by == ()

def test_project_map_version_2():
    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("/t"),
                    files=(), parse_errors=())
    assert pm.version == 2

def test_parsed_file_carries_raw_calls():
    pf = ParsedFile(path="a.py", language="python", content_hash="sha256:z",
                    symbols=(), raw_imports=(), raw_calls=(RawCall(caller="f", callee="g"),),
                    parse_error=None)
    assert pf.raw_calls[0].callee == "g"

def test_raw_call_and_raw_import():
    assert RawCall(caller="A.m", callee="helper").caller == "A.m"
    assert RawImport(text="a.b", level=0).level == 0

def test_build_progress():
    bp = BuildProgress(files_processed=1, files_total=3)
    assert (bp.files_processed, bp.files_total) == (1, 3)
