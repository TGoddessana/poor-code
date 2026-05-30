"""Public surface of project_map package."""
from __future__ import annotations

import poor_code.domain.project_map as pkg


EXPECTED_PUBLIC = {
    "BuildProgress",
    "FileEntry",
    "make_default_builder",
    "ParseError",
    "ProjectMap",
    "ProjectMapBuilder",
    "ProjectMapStore",
    "Symbol",
    "SymbolKind",
}


def test_all_set_equality():
    assert set(pkg.__all__) == EXPECTED_PUBLIC


def test_public_names_resolve():
    for name in EXPECTED_PUBLIC:
        assert hasattr(pkg, name), f"{name} not exported"


def test_internal_classes_not_exposed():
    # Internal helpers must not appear in __all__ even if submodules are
    # bound to the package object (which Python does automatically).
    for forbidden in (
        "FileDiscovery", "ImportResolver", "TestsMapper",
        "RawImport", "ParsedFile",
        "CallResolver", "RawCall",
    ):
        assert forbidden not in pkg.__all__


def test_make_default_builder_builds(tmp_path):
    from poor_code.domain.project_map import make_default_builder
    (tmp_path / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    m = make_default_builder().build(tmp_path)
    assert m.version == 2
