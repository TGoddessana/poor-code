"""Public surface for the project_map domain.

Downstream code must import from this module only. `discovery`, `parsers`,
`import_resolver`, `tests_mapping`, `paths`, `store` body, and `builder`
body are internal.
"""
from poor_code.domain.project_map.builder import ProjectMapBuilder
from poor_code.domain.project_map.models import (
    BuildProgress,
    FileEntry,
    ParseError,
    ProjectMap,
    Symbol,
    SymbolKind,
)
from poor_code.domain.project_map.store import ProjectMapStore


def make_default_builder() -> ProjectMapBuilder:
    """Construct a ProjectMapBuilder with the default V1 dependencies.

    The concrete discovery / resolver / tests_mapper classes are internal;
    downstream code should call this factory instead of importing them.
    """
    # Local import to avoid leaking submodule names into the package namespace.
    from poor_code.domain.project_map.discovery import FileDiscovery
    from poor_code.domain.project_map.import_resolver import ImportResolver
    from poor_code.domain.project_map.tests_mapping import TestsMapper
    return ProjectMapBuilder(
        discovery=FileDiscovery(),
        resolver=ImportResolver(),
        tests_mapper=TestsMapper(),
    )


__all__ = [
    "BuildProgress",
    "FileEntry",
    "make_default_builder",
    "ParseError",
    "ProjectMap",
    "ProjectMapBuilder",
    "ProjectMapStore",
    "Symbol",
    "SymbolKind",
]
