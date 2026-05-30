"""FileDiscovery — cwd recursive .py walk with .gitignore."""
from __future__ import annotations

from pathlib import Path

from poor_code.domain.project_map.discovery import FileDiscovery


def _touch(p: Path, content: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_empty_cwd_returns_empty_tuple(tmp_path: Path):
    assert FileDiscovery().discover(tmp_path) == ()


def test_picks_only_py_files(tmp_path: Path):
    _touch(tmp_path / "a.py")
    _touch(tmp_path / "b.txt")
    _touch(tmp_path / "c.pyc")
    result = FileDiscovery().discover(tmp_path)
    assert result == (tmp_path / "a.py",)


def test_walks_recursively(tmp_path: Path):
    _touch(tmp_path / "src/foo/bar.py")
    _touch(tmp_path / "src/foo/baz.py")
    _touch(tmp_path / "src/qux.py")
    result = FileDiscovery().discover(tmp_path)
    assert result == tuple(sorted([
        tmp_path / "src/foo/bar.py",
        tmp_path / "src/foo/baz.py",
        tmp_path / "src/qux.py",
    ]))


def test_hard_excludes_dot_poor_code_and_dot_git(tmp_path: Path):
    _touch(tmp_path / "src/keep.py")
    _touch(tmp_path / ".poor-code/sessions/x/state.py")
    _touch(tmp_path / ".git/hooks/post-commit.py")
    result = FileDiscovery().discover(tmp_path)
    assert result == (tmp_path / "src/keep.py",)


def test_honors_gitignore(tmp_path: Path):
    _touch(tmp_path / ".gitignore", "__pycache__/\n*.egg-info/\nnode_modules/\n")
    _touch(tmp_path / "src/keep.py")
    _touch(tmp_path / "src/__pycache__/cache.py")
    _touch(tmp_path / "pkg.egg-info/PKG-INFO.py")
    _touch(tmp_path / "node_modules/foo/bar.py")
    result = FileDiscovery().discover(tmp_path)
    assert result == (tmp_path / "src/keep.py",)


def test_missing_gitignore_only_hard_excludes(tmp_path: Path):
    # No .gitignore → __pycache__ etc. are NOT excluded by V1 (only .poor-code, .git).
    _touch(tmp_path / "src/keep.py")
    _touch(tmp_path / "build/leftover.py")
    result = FileDiscovery().discover(tmp_path)
    assert set(result) == {tmp_path / "src/keep.py", tmp_path / "build/leftover.py"}


def test_result_is_sorted(tmp_path: Path):
    _touch(tmp_path / "z.py")
    _touch(tmp_path / "a.py")
    _touch(tmp_path / "m.py")
    result = FileDiscovery().discover(tmp_path)
    assert list(result) == sorted(result)


def test_discovers_js_ts_not_unknown(tmp_path):
    from poor_code.domain.project_map.discovery import FileDiscovery
    for rel in ("a.py", "b.js", "c.ts", "d.tsx", "keep.rs", "notes.md"):
        p = tmp_path / rel
        p.write_text("x", encoding="utf-8")
    result = {p.relative_to(tmp_path).as_posix() for p in FileDiscovery().discover(tmp_path)}
    assert result == {"a.py", "b.js", "c.ts", "d.tsx"}
