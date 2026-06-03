import asyncio

import pytest

from poor_code.domain.harness.env_probe import probe_environment


@pytest.mark.asyncio
async def test_probe_reports_os_and_present_runtimes(tmp_path):
    # Runs the real probe in this environment. The test host always has a shell,
    # uname, and python3 — assert the structured sections and that a present
    # runtime is detected with detail, not just listed.
    out = await probe_environment(tmp_path)
    assert "OS:" in out
    assert "TOOLCHAIN" in out
    assert "python" in out.lower()
    # the catch-all inventory is present so long-tail tools are never silently missed
    assert "PATH COMMANDS" in out.upper() or "PATH_COMMANDS" in out


@pytest.mark.asyncio
async def test_probe_lists_absent_curated_tools(tmp_path):
    # Absence must be EXPLICIT, not merely "not in the present list" — the model
    # ignored implicit absence and kept choosing Node. The probe names what's gone.
    out = await probe_environment(tmp_path)
    assert "NOT FOUND" in out


@pytest.mark.asyncio
async def test_probe_is_bounded(tmp_path):
    out = await probe_environment(tmp_path)
    # never dump an unbounded wall of text into downstream prompts
    assert len(out) <= 8000


@pytest.mark.asyncio
async def test_probe_returns_fallback_on_failure():
    # A non-existent cwd must not raise — the probe degrades to a short marker.
    out = await probe_environment("/nonexistent/path/zzz", timeout=5)
    assert isinstance(out, str) and out  # non-empty, no exception
