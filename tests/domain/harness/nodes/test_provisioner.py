import asyncio
import json

import pytest

from poor_code.domain.harness import nodes
from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.provisioner import Provisioner, plan_commands
from poor_code.domain.session.models import EnvReport, Request, RequestKind, SessionState
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)


def _tools():
    return ToolRegistry([BashTool(), ReadTool()])


def _state():
    return SessionState(request=Request(raw_text="fix a bug", kind=RequestKind.ENGINEERING))


def _ctx():
    return NodeContext(_state(), cancel=asyncio.Event())


# --- plan_commands (deterministic prompt seed) ---

def test_plan_commands_python_project_via_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    cmds = plan_commands(tmp_path)
    assert any("pip install" in c and "-e" in c for c in cmds)


def test_plan_commands_python_project_via_setup_py(tmp_path):
    (tmp_path / "setup.py").write_text("from setuptools import setup; setup()")
    assert any("pip install" in c and "-e" in c for c in plan_commands(tmp_path))


def test_plan_commands_empty_when_no_python_marker(tmp_path):
    assert plan_commands(tmp_path) == []


# --- agentic loop: the model drives bash; we capture what it actually ran ---

class _RunThenStopLLM:
    """Stage ①: issues each scripted bash command in its own round, then stops with
    a free-text summary. There is NO structured-emit stage — that is the whole point."""

    def __init__(self, commands, summary="env is ready: pytest collects"):
        self._commands = list(commands)
        self._summary = summary
        self._i = 0

    async def stream(self, messages, tools, response_format=None):
        if self._i < len(self._commands):
            cmd = self._commands[self._i]
            self._i += 1
            cid = f"b{self._i}"
            yield ToolCallStarted(call_id=cid, name="bash")
            yield ToolCallInputDelta(call_id=cid, json_delta=json.dumps({"command": cmd}))
            yield ToolCallEnded(call_id=cid)
            yield FinishedReason(reason="tool_calls")
        else:
            yield TextDelta(text=self._summary)
            yield FinishedReason(reason="stop")


@pytest.mark.asyncio
async def test_run_captures_executed_commands_into_install_steps(tmp_path, monkeypatch):
    # Probe is deterministic and isolated from the agentic bash loop.
    monkeypatch.setattr(nodes.provisioner, "run_shell",
                        _fake_probe(code=5, out="no tests ran"))
    llm = _RunThenStopLLM(["echo configuring", "echo installing deps"])
    node = Provisioner(llm, cwd=tmp_path, tools=_tools())

    res = await node.run(_ctx())
    er = res.output
    assert isinstance(er, EnvReport)
    # The commands the AGENT chose to run become the install_steps (not a hardcoded seed).
    assert er.install_steps == ("echo configuring", "echo installing deps")


@pytest.mark.asyncio
async def test_run_ready_is_decided_by_the_probe_not_the_model(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes.provisioner, "run_shell",
                        _fake_probe(code=0, out="collected 3 items"))
    node = Provisioner(_RunThenStopLLM(["echo go"]), cwd=tmp_path, tools=_tools())

    er = (await node.run(_ctx())).output
    assert er.ready is True               # probe succeeded → ready, regardless of any emit
    assert er.test_command == "python -m pytest -q"


@pytest.mark.asyncio
async def test_run_probe_failure_yields_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes.provisioner, "run_shell",
                        _fake_probe(code=1, out="ImportError: numpy"))
    node = Provisioner(_RunThenStopLLM(["echo go"]), cwd=tmp_path, tools=_tools())

    er = (await node.run(_ctx())).output
    assert er.ready is False
    assert "numpy" in er.notes            # probe diagnostics surface in notes for the implementer


@pytest.mark.asyncio
async def test_run_needs_no_structured_emit_to_produce_a_report(tmp_path, monkeypatch):
    """The old design relied on a second LLM 'emit_env_report' call that failed 0/4 on
    weak models. The agent here never emits a structured report — yet the EnvReport is
    fully populated. This is the regression guard for that failure mode."""
    monkeypatch.setattr(nodes.provisioner, "run_shell",
                        _fake_probe(code=0, out="collected 1 item"))
    node = Provisioner(_RunThenStopLLM(["echo only-bash-no-emit"]), cwd=tmp_path, tools=_tools())

    er = (await node.run(_ctx())).output
    assert er.ready is True
    assert er.install_steps == ("echo only-bash-no-emit",)


@pytest.mark.asyncio
async def test_run_skips_probe_when_nothing_was_provisioned(tmp_path, monkeypatch):
    """Empty cwd, agent runs nothing → no point spawning pytest. Report is not-ready and
    the probe is never invoked (keeps the node a cheap no-op in greenfield/non-Python)."""
    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        raise AssertionError("probe should not run")

    monkeypatch.setattr(nodes.provisioner, "run_shell", _spy)

    class _StopImmediately:
        async def stream(self, messages, tools, response_format=None):
            yield TextDelta(text="nothing to do")
            yield FinishedReason(reason="stop")

    node = Provisioner(_StopImmediately(), cwd=tmp_path, tools=_tools())
    er = (await node.run(_ctx())).output
    assert er.ready is False
    assert er.install_steps == ()
    assert calls["n"] == 0


def _fake_probe(*, code, out):
    async def _run_shell(command, cwd, cancel, timeout=300):
        return code, out
    return _run_shell
