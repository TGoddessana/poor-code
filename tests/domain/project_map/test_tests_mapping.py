"""TestsMapper — source ↔ test file matching by name + tests/ segment."""
from __future__ import annotations

from poor_code.domain.project_map.models import ParsedFile
from poor_code.domain.project_map.tests_mapping import TestsMapper


def _pf(path: str) -> ParsedFile:
    return ParsedFile(path=path, symbols=(), raw_imports=(), parse_error=None)


def test_test_file_requires_tests_segment_and_name_pattern():
    files = (
        _pf("src/foo.py"),
        _pf("tests/test_foo.py"),       # matches
        _pf("tests/foo_test.py"),       # matches
        _pf("tests/foo.py"),            # filename doesn't match → NOT a test
        _pf("other_dir/test_foo.py"),   # no tests/ segment → NOT a test
    )
    out = TestsMapper().map(files)
    assert set(out.get("src/foo.py", ())) == {"tests/test_foo.py", "tests/foo_test.py"}


def test_test_files_themselves_have_no_tests_attached():
    files = (
        _pf("src/foo.py"),
        _pf("tests/test_foo.py"),
    )
    out = TestsMapper().map(files)
    assert out.get("tests/test_foo.py", ()) == ()


def test_multi_match_across_packages_allowed():
    files = (
        _pf("src/a/foo.py"),
        _pf("src/b/foo.py"),
        _pf("tests/test_foo.py"),
    )
    out = TestsMapper().map(files)
    assert "tests/test_foo.py" in out.get("src/a/foo.py", ())
    assert "tests/test_foo.py" in out.get("src/b/foo.py", ())


def test_source_without_matching_test_has_no_entry():
    files = (_pf("src/foo.py"),)
    out = TestsMapper().map(files)
    assert out.get("src/foo.py", ()) == ()


def test_both_test_naming_styles_match():
    files = (
        _pf("src/foo.py"),
        _pf("tests/test_foo.py"),
        _pf("tests/foo_test.py"),
    )
    out = TestsMapper().map(files)
    assert set(out["src/foo.py"]) == {"tests/test_foo.py", "tests/foo_test.py"}


def test_result_is_sorted_for_determinism():
    files = (
        _pf("src/foo.py"),
        _pf("tests/foo_test.py"),
        _pf("tests/test_foo.py"),
    )
    out = TestsMapper().map(files)
    assert list(out["src/foo.py"]) == sorted(out["src/foo.py"])
