"""ProjectMapBuilder — orchestrates the v2 graph pipeline. Internal.

discover -> parse (incremental via content_hash) -> relativize -> resolve imports
(both directions) -> resolve calls (both directions) -> map tests -> assemble v2.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from poor_code.domain.project_map import parsers
from poor_code.domain.project_map.call_resolver import CallResolver
from poor_code.domain.project_map.discovery import FileDiscovery
from poor_code.domain.project_map.import_resolver import ImportResolver
from poor_code.domain.project_map.models import (
    BuildProgress,
    FileEntry,
    ParsedFile,
    ParseError,
    ProjectMap,
    Symbol,
)
from poor_code.domain.project_map.tests_mapping import TestsMapper


class ProjectMapBuilder:
    def __init__(
        self,
        discovery: FileDiscovery,
        resolver: ImportResolver,
        call_resolver: CallResolver,
        tests_mapper: TestsMapper,
    ) -> None:
        self._discovery = discovery
        self._resolver = resolver
        self._call_resolver = call_resolver
        self._tests_mapper = tests_mapper
        self._last_parsed: tuple[ParsedFile, ...] = ()

    def build(
        self,
        cwd: Path,
        on_progress: Callable[[BuildProgress], None] | None = None,
        previous_parsed: tuple[ParsedFile, ...] | None = None,
    ) -> ProjectMap:
        paths = self._discovery.discover(cwd)
        total = len(paths)
        cache = {pf.path: pf for pf in previous_parsed} if previous_parsed else {}

        parsed_rel: list[ParsedFile] = []
        for i, p in enumerate(paths):
            rel = p.relative_to(cwd).as_posix()
            digest = (
                "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
                if p.is_file()
                else ""
            )
            cached = cache.get(rel)
            if cached is not None and digest and cached.content_hash == digest:
                parsed_rel.append(cached)
            else:
                parsed_rel.append(self._relativize(parsers.parse_file(p), cwd))
            if on_progress is not None:
                on_progress(BuildProgress(files_processed=i + 1, files_total=total))
        parsed_rel = tuple(parsed_rel)
        self._last_parsed = parsed_rel

        imports, imported_by = self._resolver.resolve(parsed_rel)
        calls, called_by = self._call_resolver.resolve(parsed_rel)
        tests = self._tests_mapper.map(parsed_rel)

        files = tuple(
            FileEntry(
                path=pf.path,
                language=pf.language,
                content_hash=pf.content_hash,
                symbols=tuple(
                    Symbol(
                        name=s.name,
                        kind=s.kind,
                        lineno=s.lineno,
                        signature=s.signature,
                        doc=s.doc,
                        calls=calls.get((pf.path, s.name), ()),
                        called_by=called_by.get((pf.path, s.name), ()),
                    )
                    for s in pf.symbols
                ),
                imports=imports.get(pf.path, ()),
                imported_by=imported_by.get(pf.path, ()),
                tests=tests.get(pf.path, ()),
            )
            for pf in parsed_rel
            if pf.parse_error is None
        )
        parse_errors = tuple(
            pf.parse_error for pf in parsed_rel if pf.parse_error is not None
        )
        return ProjectMap(
            version=2,
            generated_at=datetime.now(UTC),
            cwd=cwd,
            files=files,
            parse_errors=parse_errors,
        )

    @staticmethod
    def _relativize(pf: ParsedFile, cwd: Path) -> ParsedFile:
        rel = Path(pf.path).relative_to(cwd).as_posix()
        err = (
            ParseError(path=rel, error=pf.parse_error.error)
            if pf.parse_error
            else None
        )
        return ParsedFile(
            path=rel,
            language=pf.language,
            content_hash=pf.content_hash,
            symbols=pf.symbols,
            raw_imports=pf.raw_imports,
            raw_calls=pf.raw_calls,
            parse_error=err,
        )
