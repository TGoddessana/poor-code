"""ImportResolver — RawImport -> internal cwd-relative POSIX paths, both directions.

Internal. No I/O: resolves against the set of known internal files. Python imports
resolve via a dotted-module index built across candidate source roots (handles
src-layout); relative (level>0) imports resolve against the importer's directory.
JS/TS imports resolve relative specifiers (./ ../) to internal files.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from poor_code.domain.project_map.models import ParsedFile

_PY_EXT = ".py"
_JS_TS_INDEX = ("index.ts", "index.tsx", "index.js", "index.jsx")


class ImportResolver:
    def resolve(
        self, parsed_files: tuple[ParsedFile, ...]
    ) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
        universe: set[str] = {pf.path for pf in parsed_files}
        module_index = self._build_python_module_index(universe)

        imports: dict[str, tuple[str, ...]] = {}
        for pf in parsed_files:
            if not pf.raw_imports:
                continue
            resolved: list[str] = []
            seen: set[str] = set()
            for ri in pf.raw_imports:
                if pf.language == "python":
                    target = self._resolve_python(pf.path, ri, module_index, universe)
                else:
                    target = self._resolve_relative_path(pf.path, ri.text, universe)
                if target is None or target == pf.path or target in seen:
                    continue
                seen.add(target)
                resolved.append(target)
            if resolved:
                imports[pf.path] = tuple(resolved)

        imported_by: dict[str, list[str]] = {}
        for src, targets in imports.items():
            for t in targets:
                imported_by.setdefault(t, []).append(src)
        imported_by_sorted = {k: tuple(sorted(v)) for k, v in imported_by.items()}
        return imports, imported_by_sorted

    # --- Python ---
    @staticmethod
    def _source_roots(universe: set[str]) -> list[str]:
        roots = [""]
        if any(p.startswith("src/") for p in universe):
            roots.append("src")
        return roots

    def _build_python_module_index(self, universe: set[str]) -> dict[str, str]:
        # dotted module name -> file path. Prefer module file over __init__.
        index: dict[str, str] = {}
        roots = self._source_roots(universe)
        for path in universe:
            if not path.endswith(_PY_EXT):
                continue
            for root in roots:
                rel = path
                if root:
                    prefix = root + "/"
                    if not path.startswith(prefix):
                        continue
                    rel = path[len(prefix):]
                noext = rel[: -len(_PY_EXT)]
                parts = noext.split("/")
                if parts[-1] == "__init__":
                    dotted = ".".join(parts[:-1])
                    index.setdefault(dotted, path)  # package -> __init__
                else:
                    dotted = ".".join(parts)
                    index[dotted] = path  # module file wins (overwrite __init__)
        # Double-registration across source roots is intentional and harmless: a file
        # like src/foo.py registers both "foo" (correct) and "src.foo" (phantom that
        # only matches the incorrect `import src.foo` and is otherwise inert).
        return index

    def _resolve_python(self, src_path, ri, module_index, universe):
        if ri.level == 0:
            return module_index.get(ri.text)
        # relative: compute base package dir of importer, ascend (level-1)
        pkg_parts = PurePosixPath(src_path).parts[:-1]
        ascend = ri.level - 1
        if ascend > len(pkg_parts):
            return None
        base_parts = pkg_parts[: len(pkg_parts) - ascend] if ascend else pkg_parts
        base = PurePosixPath(*base_parts) if base_parts else PurePosixPath("")
        if ri.text:
            target = base / PurePosixPath(*ri.text.split("."))
            cands = [f"{target.as_posix()}.py", f"{target.as_posix()}/__init__.py"]
        else:
            b = base.as_posix()
            cands = [f"{b}/__init__.py" if b != "." else "__init__.py"]
        for c in (c.removeprefix("./") for c in cands):
            if c in universe:
                return c
        return None

    # --- JS/TS ---
    @staticmethod
    def _normalize(path: str) -> str:
        # Collapse "." and ".." segments without filesystem resolution.
        out: list[str] = []
        for seg in path.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if out and out[-1] != "..":
                    out.pop()
                else:
                    out.append("..")
            else:
                out.append(seg)
        return "/".join(out)

    @classmethod
    def _resolve_relative_path(cls, src_path: str, spec: str, universe: set[str]) -> str | None:
        if not spec.startswith("."):
            return None  # bare/package specifier -> external
        base = PurePosixPath(src_path).parent
        target = cls._normalize(f"{base.as_posix()}/{spec}")
        if PurePosixPath(target).suffix:
            cands = [target]
        else:
            cands = [
                f"{target}.ts", f"{target}.tsx", f"{target}.js", f"{target}.jsx",
                *(f"{target}/{i}" for i in _JS_TS_INDEX),
            ]
        for c in cands:
            if c in universe:
                return c
        return None
