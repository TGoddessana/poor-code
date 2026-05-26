"""ProjectMapBuilder — orchestrates the pipeline.

Internal. discovery → parse (with optional progress) → import resolution
→ tests mapping → assembly. Path normalization (absolute → cwd-relative
POSIX) happens here so parsers stay cwd-unaware.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from poor_code.domain.project_map import parsers
from poor_code.domain.project_map.discovery import FileDiscovery
from poor_code.domain.project_map.import_resolver import ImportResolver
from poor_code.domain.project_map.models import (
    BuildProgress,
    FileEntry,
    ParsedFile,
    ParseError,
    ProjectMap,
)
from poor_code.domain.project_map.tests_mapping import TestsMapper


class ProjectMapBuilder:
    def __init__(
        self,
        discovery: FileDiscovery,
        resolver: ImportResolver,
        tests_mapper: TestsMapper,
    ) -> None:
        self._discovery = discovery
        self._resolver = resolver
        self._tests_mapper = tests_mapper

    def build(
        self,
        cwd: Path,
        on_progress: Callable[[BuildProgress], None] | None = None,
    ) -> ProjectMap:
        paths = self._discovery.discover(cwd)
        total = len(paths)

        parsed_abs: list[ParsedFile] = []
        for i, p in enumerate(paths):
            parsed_abs.append(parsers.parse_file(p))
            if on_progress is not None:
                on_progress(BuildProgress(files_processed=i + 1, files_total=total))

        parsed_rel = tuple(self._relativize(pf, cwd) for pf in parsed_abs)
        resolved = self._resolver.resolve(parsed_rel)
        tests = self._tests_mapper.map(parsed_rel)

        files = tuple(
            FileEntry(
                path=pf.path,
                symbols=pf.symbols,
                imports=resolved.get(pf.path, ()),
                tests=tests.get(pf.path, ()),
            )
            for pf in parsed_rel
            if pf.parse_error is None
        )
        parse_errors = tuple(
            pf.parse_error for pf in parsed_rel if pf.parse_error is not None
        )

        return ProjectMap(
            version=1,
            generated_at=datetime.now(UTC),
            cwd=cwd,
            files=files,
            parse_errors=parse_errors,
        )

    @staticmethod
    def _relativize(pf: ParsedFile, cwd: Path) -> ParsedFile:
        rel = Path(pf.path).relative_to(cwd).as_posix()
        new_err = (
            ParseError(path=rel, error=pf.parse_error.error)
            if pf.parse_error is not None
            else None
        )
        return ParsedFile(
            path=rel,
            symbols=pf.symbols,
            raw_imports=pf.raw_imports,
            parse_error=new_err,
        )
