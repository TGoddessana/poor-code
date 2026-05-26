"""ProjectMapStore — atomic JSON write, schema-faithful read."""
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


def _sample(cwd: Path) -> ProjectMap:
    return ProjectMap(
        version=1,
        generated_at=datetime(2026, 5, 27, 12, 34, 56, tzinfo=UTC),
        cwd=cwd,
        files=(
            FileEntry(
                path="src/foo.py",
                symbols=(
                    Symbol(name="Foo", kind=SymbolKind.CLASS, lineno=1),
                    Symbol(name="Foo.bar", kind=SymbolKind.METHOD, lineno=2),
                ),
                imports=("src/baz.py",),
                tests=("tests/test_foo.py",),
            ),
        ),
        parse_errors=(ParseError(path="src/broken.py", error="SyntaxError: ..."),),
    )


def test_write_read_roundtrip_preserves_all_fields(tmp_path: Path):
    root = tmp_path / ".poor-code"
    store = ProjectMapStore()
    original = _sample(tmp_path)
    store.write(original, root)
    loaded = store.read(root)
    assert loaded == original


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


def test_corrupt_json_raises_value_error(tmp_path: Path):
    root = tmp_path / ".poor-code"
    root.mkdir()
    (root / "project_map.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt project map"):
        ProjectMapStore().read(root)


def test_unknown_enum_value_raises_value_error(tmp_path: Path):
    root = tmp_path / ".poor-code"
    root.mkdir()
    bad = {
        "version": 1,
        "generated_at": "2026-05-27T12:34:56+00:00",
        "cwd": str(tmp_path),
        "files": [{"path": "x.py", "symbols": [{"name": "X", "kind": "BOGUS", "lineno": 1}], "imports": [], "tests": []}],
        "parse_errors": [],
    }
    (root / "project_map.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt project map"):
        ProjectMapStore().read(root)
