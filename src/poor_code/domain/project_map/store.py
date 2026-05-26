"""ProjectMapStore — atomic JSON I/O for project_map.json.

Internal. Mirrors the atomic-write pattern in domain/session/store.py.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from poor_code.domain.project_map import paths
from poor_code.domain.project_map.models import (
    FileEntry,
    ParseError,
    ProjectMap,
    Symbol,
    SymbolKind,
)


class ProjectMapStore:
    def write(self, project_map: ProjectMap, root: Path) -> None:
        _atomic_write_json(paths.project_map_json(root), _map_to_dict(project_map))

    def read(self, root: Path) -> ProjectMap:
        path = paths.project_map_json(root)
        return _dict_to_map(_read_json(path), path)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"corrupt project map at {path}: {e}") from e


def _map_to_dict(m: ProjectMap) -> dict[str, Any]:
    return {
        "version": m.version,
        "generated_at": m.generated_at.isoformat(),
        "cwd": str(m.cwd),
        "files": [_file_to_dict(fe) for fe in m.files],
        "parse_errors": [{"path": pe.path, "error": pe.error} for pe in m.parse_errors],
    }


def _file_to_dict(fe: FileEntry) -> dict[str, Any]:
    return {
        "path": fe.path,
        "symbols": [
            {"name": s.name, "kind": s.kind.value, "lineno": s.lineno}
            for s in fe.symbols
        ],
        "imports": list(fe.imports),
        "tests": list(fe.tests),
    }


def _dict_to_map(d: dict[str, Any], src: Path) -> ProjectMap:
    try:
        return ProjectMap(
            version=d["version"],
            generated_at=datetime.fromisoformat(d["generated_at"]),
            cwd=Path(d["cwd"]),
            files=tuple(_dict_to_file(fd, src) for fd in d["files"]),
            parse_errors=tuple(
                ParseError(path=pe["path"], error=pe["error"])
                for pe in d["parse_errors"]
            ),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"corrupt project map at {src}: {e}") from e


def _dict_to_file(fd: dict[str, Any], src: Path) -> FileEntry:
    return FileEntry(
        path=fd["path"],
        symbols=tuple(
            Symbol(name=s["name"], kind=SymbolKind(s["kind"]), lineno=s["lineno"])
            for s in fd["symbols"]
        ),
        imports=tuple(fd["imports"]),
        tests=tuple(fd["tests"]),
    )
