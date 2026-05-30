"""ProjectMapStore — atomic JSON write, schema-faithful read (v2)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from poor_code.domain.project_map.models import (
    FileEntry,
    ParseError,
    ProjectMap,
    Symbol,
    SymbolKind,
)
from poor_code.domain.project_map.store import ProjectMapStore


def _sample(cwd):
    return ProjectMap(
        version=2, generated_at=datetime(2026,5,30,12,0,0,tzinfo=UTC), cwd=cwd,
        files=(FileEntry(
            path="src/foo.py", language="python", content_hash="sha256:abc",
            symbols=(Symbol(name="Foo.bar", kind=SymbolKind.METHOD, lineno=2,
                            signature="(self) -> None", doc="Do.",
                            calls=("src/foo.py::helper",), called_by=()),),
            imports=("src/baz.py",), imported_by=("src/cli.py",), tests=("tests/test_foo.py",)),),
        parse_errors=(ParseError(path="src/bad.py", error="SyntaxError: ..."),))


def test_roundtrip(tmp_path):
    root = tmp_path / ".poor-code"
    store = ProjectMapStore(); orig = _sample(tmp_path)
    store.write(orig, root)
    assert store.read(root) == orig


def test_version_is_2_on_disk(tmp_path):
    root = tmp_path / ".poor-code"
    ProjectMapStore().write(_sample(tmp_path), root)
    data = json.loads((root / "project_map.json").read_text())
    assert data["version"] == 2
    assert data["files"][0]["language"] == "python"
    assert data["files"][0]["symbols"][0]["signature"] == "(self) -> None"


def test_null_signature_roundtrips(tmp_path):
    root = tmp_path / ".poor-code"
    pm = ProjectMap(version=2, generated_at=datetime(2026,5,30,tzinfo=UTC), cwd=tmp_path,
        files=(FileEntry(path="a.py", language="python", content_hash="sha256:z",
            symbols=(Symbol(name="f", kind=SymbolKind.FUNCTION, lineno=1,
                            signature=None, doc=None, calls=(), called_by=()),),
            imports=(), imported_by=(), tests=()),), parse_errors=())
    ProjectMapStore().write(pm, root)
    assert ProjectMapStore().read(root) == pm


def test_corrupt_json_raises(tmp_path):
    root = tmp_path / ".poor-code"; root.mkdir()
    (root / "project_map.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt project map"):
        ProjectMapStore().read(root)


def test_write_is_atomic_no_tmp_leftover(tmp_path: Path):
    root = tmp_path / ".poor-code"
    ProjectMapStore().write(_sample(tmp_path), root)
    leftovers = list(root.glob("*.tmp"))
    assert leftovers == []


def test_write_cleans_up_tmp_on_failure(tmp_path: Path):
    root = tmp_path / ".poor-code"
    root.mkdir()
    with patch("os.replace", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            ProjectMapStore().write(_sample(tmp_path), root)
    assert list(root.glob("*.tmp")) == []
