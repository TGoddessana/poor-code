"""FileDiscovery — cwd-recursive multi-language walk honoring root .gitignore.

Internal — do not import outside this package.
"""
from __future__ import annotations

from pathlib import Path

import pathspec

from poor_code.domain.project_map.languages import EXTENSION_TO_LANGUAGE


_HARD_EXCLUDED_DIRS = (".poor-code", ".git")


class FileDiscovery:
    def discover(self, cwd: Path) -> tuple[Path, ...]:
        spec = self._load_gitignore(cwd)
        results: list[Path] = []
        for p in cwd.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in EXTENSION_TO_LANGUAGE:
                continue
            if self._is_hard_excluded(p, cwd):
                continue
            rel = p.relative_to(cwd).as_posix()
            if spec.match_file(rel):
                continue
            results.append(p)
        return tuple(sorted(results))

    @staticmethod
    def _load_gitignore(cwd: Path) -> pathspec.PathSpec:
        gi = cwd / ".gitignore"
        if not gi.is_file():
            return pathspec.PathSpec.from_lines("gitwildmatch", [])
        return pathspec.PathSpec.from_lines("gitwildmatch", gi.read_text(encoding="utf-8").splitlines())

    @staticmethod
    def _is_hard_excluded(p: Path, cwd: Path) -> bool:
        parts = p.relative_to(cwd).parts
        return any(part in _HARD_EXCLUDED_DIRS for part in parts)
