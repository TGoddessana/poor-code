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

__all__ = [
    "BuildProgress",
    "FileEntry",
    "ParseError",
    "ProjectMap",
    "ProjectMapBuilder",
    "ProjectMapStore",
    "Symbol",
    "SymbolKind",
]
