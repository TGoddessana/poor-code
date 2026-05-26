from pathlib import Path
from unittest.mock import patch

import pytest

from poor_code.domain.session.store import _atomic_write_json


def test_atomic_write_creates_file(tmp_path: Path):
    target = tmp_path / "sub" / "out.json"
    _atomic_write_json(target, {"k": "v"})
    assert target.exists()
    assert '"k": "v"' in target.read_text(encoding="utf-8")


def test_atomic_write_overwrites_existing(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")
    _atomic_write_json(target, {"new": True})
    assert "new" in target.read_text(encoding="utf-8")
    assert "old" not in target.read_text(encoding="utf-8")


def test_atomic_write_failure_preserves_original(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text('{"original": true}', encoding="utf-8")

    with patch("os.replace", side_effect=OSError("simulated disk error")):
        with pytest.raises(OSError, match="simulated"):
            _atomic_write_json(target, {"new": True})

    # Original survives.
    assert "original" in target.read_text(encoding="utf-8")
    assert "new" not in target.read_text(encoding="utf-8")


def test_atomic_write_no_tmp_file_left_on_success(tmp_path: Path):
    target = tmp_path / "out.json"
    _atomic_write_json(target, {"k": "v"})
    assert target.exists()
    # No .tmp sibling.
    assert not (tmp_path / "out.json.tmp").exists()


def test_atomic_write_failure_cleans_up_tmp_file(tmp_path: Path):
    target = tmp_path / "out.json"
    target.write_text('{"original": true}', encoding="utf-8")

    with patch("os.replace", side_effect=OSError("simulated")):
        with pytest.raises(OSError):
            _atomic_write_json(target, {"new": True})

    # Stale .tmp should not remain.
    assert not (tmp_path / "out.json.tmp").exists()
    # Original still intact.
    assert "original" in target.read_text(encoding="utf-8")
