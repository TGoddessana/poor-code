import asyncio

import pytest

from poor_code.domain.harness import api_probe
from poor_code.domain.harness.api_probe import (
    _imports_from, _is_third_party, _select_symbols, focus_terms, probe_apis,
)
from poor_code.domain.session.models import FileExcerpt


def test_imports_from_extracts_from_and_plain_imports():
    src = (
        "from textual.widgets import Input, TextArea\n"
        "import os\n"
        "from . import local_thing\n"
        "import textual.app as app\n"
    )
    pairs = _imports_from(src)
    assert ("textual.widgets", "Input") in pairs
    assert ("textual.widgets", "TextArea") in pairs
    assert ("os", "os") in pairs
    assert ("textual.app", "app") in pairs
    # relative import (level>0) is skipped
    assert all(mod != "" for mod, _ in pairs)


def test_imports_from_tolerates_syntax_error():
    assert _imports_from("def broken(:\n") == []


def test_is_third_party_filters_stdlib_and_local():
    assert _is_third_party("textual.widgets") is True
    assert _is_third_party("os") is False
    assert _is_third_party("asyncio") is False
    assert _is_third_party("poor_code.ui") is False
    assert _is_third_party(".relative") is False


def test_select_symbols_prioritises_focus_then_classes_and_skips_lowercase():
    excerpts = (FileExcerpt(path="p.py", text=(
        "from textual.widgets import Input, TextArea\n"
        "from textual.app import App\n"
        "from json import loads\n")),)
    # 'TextArea' is named in the requirement → must rank first; lowercase 'loads'
    # (not class-like, not in focus) is dropped.
    selected = _select_symbols(excerpts, focus_terms("switch to a TextArea"))
    assert selected[0] == ("textual.widgets", "TextArea")
    names = [n for _, n in selected]
    assert "Input" in names and "App" in names
    assert "loads" not in names  # from `json` (stdlib) anyway, and lowercase


def test_focus_terms_tokenises_identifiers():
    terms = focus_terms("change Input to TextArea (multiline)")
    assert "TextArea" in terms and "Input" in terms and "multiline" in terms


@pytest.mark.asyncio
async def test_probe_apis_reports_real_attrs(monkeypatch, tmp_path):
    calls = []

    async def fake_run_shell(command, cwd, cancel, *a, **k):
        calls.append(command)
        # emulate the probe printing the public attribute list
        return 0, "text, insert, clear, focus"

    monkeypatch.setattr(api_probe, "run_shell", fake_run_shell)
    excerpts = (FileExcerpt(path="p.py", text="from textual.widgets import TextArea\n"),)
    digest = await probe_apis(excerpts, focus_terms("TextArea"), tmp_path, asyncio.Event())
    assert "textual.widgets.TextArea public attrs: text, insert, clear, focus" in digest
    assert calls  # a probe command was actually issued


@pytest.mark.asyncio
async def test_probe_apis_marks_unavailable_on_failure(monkeypatch, tmp_path):
    async def fake_run_shell(command, cwd, cancel, *a, **k):
        return 1, "ModuleNotFoundError: no such module"

    monkeypatch.setattr(api_probe, "run_shell", fake_run_shell)
    excerpts = (FileExcerpt(path="p.py", text="from nope_lib import Widget\n"),)
    digest = await probe_apis(excerpts, focus_terms(""), tmp_path, asyncio.Event())
    assert "nope_lib.Widget: <unavailable>" in digest


@pytest.mark.asyncio
async def test_probe_apis_empty_when_no_third_party(tmp_path):
    excerpts = (FileExcerpt(path="p.py", text="import os\nimport sys\n"),)
    digest = await probe_apis(excerpts, focus_terms(""), tmp_path, asyncio.Event())
    assert digest == ""
