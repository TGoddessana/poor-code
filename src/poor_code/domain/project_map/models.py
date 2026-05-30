"""Frozen dataclasses for the project_map domain (schema v2).

Persistent: Symbol, FileEntry, ParseError, ProjectMap.
Intermediate (not persisted): RawImport, RawCall, ParsedFile, BuildProgress.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class SymbolKind(str, Enum):
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: SymbolKind
    lineno: int
    signature: str | None
    doc: str | None
    calls: tuple[str, ...]
    called_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    language: str
    content_hash: str
    symbols: tuple[Symbol, ...]
    imports: tuple[str, ...]
    imported_by: tuple[str, ...]
    tests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParseError:
    path: str
    error: str


@dataclass(frozen=True, slots=True)
class ProjectMap:
    version: int
    generated_at: datetime
    cwd: Path
    files: tuple[FileEntry, ...]
    parse_errors: tuple[ParseError, ...]


@dataclass(frozen=True, slots=True)
class RawImport:
    text: str
    level: int


@dataclass(frozen=True, slots=True)
class RawCall:
    caller: str   # qualified symbol name of the enclosing definition ("" if module-level)
    callee: str   # bare called name as written


@dataclass(frozen=True, slots=True)
class ParsedFile:
    path: str
    language: str
    content_hash: str
    symbols: tuple[Symbol, ...]
    raw_imports: tuple[RawImport, ...]
    raw_calls: tuple[RawCall, ...]
    parse_error: ParseError | None


@dataclass(frozen=True, slots=True)
class BuildProgress:
    files_processed: int
    files_total: int
