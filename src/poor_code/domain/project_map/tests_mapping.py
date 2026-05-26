"""TestsMapper — name-based source↔test matching.

Internal. A test file has `tests/` as a path segment and a filename of
`test_*.py` or `*_test.py`. A non-test source `<dir>/foo.py` is matched
to any test whose filename equals `test_foo.py` or `foo_test.py`.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from poor_code.domain.project_map.models import ParsedFile


class TestsMapper:
    def map(self, parsed_files: tuple[ParsedFile, ...]) -> dict[str, tuple[str, ...]]:
        test_files: list[tuple[str, str]] = []
        sources: list[tuple[str, str]] = []
        for pf in parsed_files:
            posix = PurePosixPath(pf.path)
            stem = posix.stem
            if self._is_test_file(posix):
                test_files.append((pf.path, stem))
            else:
                sources.append((pf.path, stem))

        out: dict[str, tuple[str, ...]] = {}
        for src_path, src_stem in sources:
            expected = (f"test_{src_stem}", f"{src_stem}_test")
            matches = sorted(
                t_path for t_path, t_stem in test_files if t_stem in expected
            )
            if matches:
                out[src_path] = tuple(matches)
        return out

    @staticmethod
    def _is_test_file(p: PurePosixPath) -> bool:
        if "tests" not in p.parts:
            return False
        name = p.name
        if name.startswith("test_") and name.endswith(".py"):
            return True
        if name.endswith("_test.py"):
            return True
        return False
