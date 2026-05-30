"""TestsMapper — name-based source↔test matching.

Internal. A Python test file has `tests/` as a path segment and a filename of
`test_*.py` or `*_test.py`. A non-test source `<dir>/foo.py` is matched to any
test whose filename equals `test_foo.py` or `foo_test.py`.

JS/TS conventions are also supported (no `tests/` segment required): a test
file `<dir>/foo.test.ts` (or `.spec.ts`, and `.tsx`/`.js` variants) matches a
source whose stem is `foo`, e.g. `web/util.test.ts` → `web/util.ts`.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from poor_code.domain.project_map.models import ParsedFile

_JS_TS_TEST_SUFFIXES = (
    ".test.ts",
    ".spec.ts",
    ".test.tsx",
    ".spec.tsx",
    ".test.js",
    ".spec.js",
)


class TestsMapper:
    def map(self, parsed_files: tuple[ParsedFile, ...]) -> dict[str, tuple[str, ...]]:
        # test files carry the source stem they target (derived from name pattern)
        test_files: list[tuple[str, str]] = []
        sources: list[tuple[str, str]] = []
        for pf in parsed_files:
            posix = PurePosixPath(pf.path)
            if self._is_test_file(posix):
                target = self._targets_stem(posix)
                if target is not None:
                    test_files.append((pf.path, target))
            else:
                sources.append((pf.path, posix.stem))

        out: dict[str, tuple[str, ...]] = {}
        for src_path, src_stem in sources:
            matches = sorted(
                t_path for t_path, t_target in test_files if t_target == src_stem
            )
            if matches:
                out[src_path] = tuple(matches)
        return out

    @staticmethod
    def _is_test_file(p: PurePosixPath) -> bool:
        name = p.name
        if "tests" in p.parts:
            if name.startswith("test_") and name.endswith(".py"):
                return True
            if name.endswith("_test.py"):
                return True
        # JS/TS conventions (no tests/ segment required)
        return any(name.endswith(suf) for suf in _JS_TS_TEST_SUFFIXES)

    @staticmethod
    def _targets_stem(p: PurePosixPath) -> str | None:
        name = p.name
        if "tests" in p.parts:
            if name.startswith("test_") and name.endswith(".py"):
                return name[len("test_") : -len(".py")]
            if name.endswith("_test.py"):
                return name[: -len("_test.py")]
        for suf in _JS_TS_TEST_SUFFIXES:
            if name.endswith(suf):
                return name[: -len(suf)]
        return None
