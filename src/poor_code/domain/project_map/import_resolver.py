"""ImportResolver — RawImport → resolved internal cwd-relative POSIX paths.

Internal. Resolves against the set of known internal files (no I/O), so
all input paths must already be cwd-relative POSIX.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from poor_code.domain.project_map.models import ParsedFile


class ImportResolver:
    def resolve(self, parsed_files: tuple[ParsedFile, ...]) -> dict[str, tuple[str, ...]]:
        universe: set[str] = {pf.path for pf in parsed_files}
        out: dict[str, tuple[str, ...]] = {}
        for pf in parsed_files:
            if not pf.raw_imports:
                continue
            resolved: list[str] = []
            seen: set[str] = set()
            for ri in pf.raw_imports:
                target = self._resolve_one(pf.path, ri.text, ri.level, universe)
                if target is None:
                    continue
                if target == pf.path:
                    continue
                if target in seen:
                    continue
                seen.add(target)
                resolved.append(target)
            if resolved:
                out[pf.path] = tuple(resolved)
        return out

    @staticmethod
    def _resolve_one(
        src_path: str, text: str, level: int, universe: set[str]
    ) -> str | None:
        if level == 0:
            base = PurePosixPath("")
        else:
            src_parts = PurePosixPath(src_path).parts
            # Drop the filename; then go up (level - 1) directories from there.
            ascend = level - 1
            pkg_parts = src_parts[:-1]  # directory containing the file
            if ascend > len(pkg_parts):
                return None
            base = PurePosixPath(*pkg_parts[: len(pkg_parts) - ascend]) if ascend else PurePosixPath(*pkg_parts)

        if text:
            target_base = base / PurePosixPath(*text.split("."))
            candidates = [
                f"{target_base.as_posix()}.py",
                f"{target_base.as_posix()}/__init__.py",
            ]
        else:
            # `from . import x` style — resolve to the package's __init__.
            candidates = [f"{base.as_posix()}/__init__.py" if base.as_posix() != "." else "__init__.py"]
        # PurePosixPath("") yields "." which is unhelpful; normalize.
        candidates = [c.removeprefix("./") for c in candidates]
        for c in candidates:
            if c in universe:
                return c
        return None
