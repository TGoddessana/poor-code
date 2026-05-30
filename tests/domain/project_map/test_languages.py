from pathlib import Path
from poor_code.domain.project_map import languages

def test_extension_dispatch():
    assert languages.detect_language(Path("a.py")) == "python"
    assert languages.detect_language(Path("a.js")) == "javascript"
    assert languages.detect_language(Path("a.mjs")) == "javascript"
    assert languages.detect_language(Path("a.ts")) == "typescript"
    assert languages.detect_language(Path("a.tsx")) == "typescript"

def test_unknown_extension_returns_none(tmp_path):
    assert languages.detect_language(tmp_path / "a.rs") is None

def test_shebang_fallback_for_extensionless(tmp_path):
    f = tmp_path / "runme"
    f.write_text("#!/usr/bin/env python3\nprint(1)\n", encoding="utf-8")
    assert languages.detect_language(f) == "python"

def test_shebang_node(tmp_path):
    f = tmp_path / "tool"
    f.write_text("#!/usr/bin/env node\nconsole.log(1)\n", encoding="utf-8")
    assert languages.detect_language(f) == "javascript"

def test_extensionless_no_shebang_is_none(tmp_path):
    f = tmp_path / "data"
    f.write_text("just text\n", encoding="utf-8")
    assert languages.detect_language(f) is None

def test_first_class_tier():
    for lang in ("python", "javascript", "typescript"):
        assert languages.TIER[lang] == "first"
