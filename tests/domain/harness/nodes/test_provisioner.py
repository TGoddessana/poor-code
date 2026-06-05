import asyncio

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes import provisioner as prov
from poor_code.domain.harness.nodes.provisioner import Provisioner, plan_commands
from poor_code.domain.session.models import SessionState, VerdictKind


def test_plan_commands_python_project_via_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    cmds = plan_commands(tmp_path)
    assert any("pip install" in c and "-e" in c for c in cmds)
    assert any("pytest" in c for c in cmds)


def test_plan_commands_python_project_via_setup_py(tmp_path):
    (tmp_path / "setup.py").write_text("from setuptools import setup; setup()")
    cmds = plan_commands(tmp_path)
    assert any("pip install" in c and "-e" in c for c in cmds)


def test_plan_commands_empty_when_no_python_marker(tmp_path):
    assert plan_commands(tmp_path) == []


@pytest.mark.asyncio
async def test_run_executes_each_command_and_advances(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    calls = []

    async def fake_run_shell(cmd, cwd, cancel, timeout=0):
        calls.append(cmd)
        return 0, "ok"

    monkeypatch.setattr(prov, "run_shell", fake_run_shell)
    res = await Provisioner(cwd=tmp_path).run(
        NodeContext(SessionState(), cancel=asyncio.Event()))
    assert calls == plan_commands(tmp_path)
    assert len(calls) > 0
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_run_advances_even_when_commands_fail(tmp_path, monkeypatch):
    (tmp_path / "setup.py").write_text("from setuptools import setup; setup()")

    async def fake_run_shell(cmd, cwd, cancel, timeout=0):
        return 1, "boom"

    monkeypatch.setattr(prov, "run_shell", fake_run_shell)
    res = await Provisioner(cwd=tmp_path).run(
        NodeContext(SessionState(), cancel=asyncio.Event()))
    assert res.verdict.kind is VerdictKind.ADVANCE


@pytest.mark.asyncio
async def test_run_noops_when_no_python_project(tmp_path, monkeypatch):
    called = False

    async def fake_run_shell(*a, **k):
        nonlocal called
        called = True
        return 0, ""

    monkeypatch.setattr(prov, "run_shell", fake_run_shell)
    res = await Provisioner(cwd=tmp_path).run(
        NodeContext(SessionState(), cancel=asyncio.Event()))
    assert called is False
    assert res.verdict.kind is VerdictKind.ADVANCE
