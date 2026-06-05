import asyncio
import json

import pytest

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


# --- plan_commands (deterministic seed/fallback) ---

def test_plan_commands_python_project_via_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    cmds = plan_commands(tmp_path)
    assert any("pip install" in c and "-e" in c for c in cmds)
    assert any("pytest" in c for c in cmds)


def test_plan_commands_python_project_via_setup_py(tmp_path):
    (tmp_path / "setup.py").write_text("from setuptools import setup; setup()")
    assert any("pip install" in c and "-e" in c for c in plan_commands(tmp_path))


def test_plan_commands_empty_when_no_python_marker(tmp_path):
    assert plan_commands(tmp_path) == []


# --- agentic run ---

class _ProvisionLLM:
    """Stage ① runs one bash round then stops; stage ② emits an env report."""
    def __init__(self):
        self.rounds = 0

    async def stream(self, messages, tools, response_format=None):
        names = [t["function"]["name"] for t in tools]
        if "emit_env_report" in names:  # stage ② extraction
            yield ToolCallStarted(call_id="e1", name="emit_env_report")
            yield ToolCallInputDelta(call_id="e1", json_delta=json.dumps({
                "ready": True, "test_command": "pytest -q",
                "install_steps": ["python -m pip install -e .[test]"],
                "notes": "deps installed"}))
            yield ToolCallEnded(call_id="e1")
            yield FinishedReason(reason="tool_calls")
            return
        self.rounds += 1
        if self.rounds == 1:  # stage ① one bash command
            yield ToolCallStarted(call_id="b1", name="bash")
            yield ToolCallInputDelta(call_id="b1", json_delta=json.dumps({"command": "echo hi"}))
            yield ToolCallEnded(call_id="b1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield TextDelta(text="done")
            yield FinishedReason(reason="stop")


@pytest.mark.asyncio
async def test_run_emits_env_report(tmp_path):
    node = Provisioner(_ProvisionLLM(), cwd=tmp_path, tools=_tools())
    res = await node.run(NodeContext(_state(), cancel=asyncio.Event()))
    er = res.output
    assert isinstance(er, EnvReport)
    assert er.ready is True
    assert er.test_command == "pytest -q"
    assert er.install_steps == ("python -m pip install -e .[test]",)


class _NoReportLLM:
    """Never calls a tool — stage ① stops at once, stage ② can't emit a report."""
    async def stream(self, messages, tools, response_format=None):
        yield TextDelta(text="...")
        yield FinishedReason(reason="stop")


@pytest.mark.asyncio
async def test_run_falls_back_to_seed_when_no_structured_report(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    node = Provisioner(_NoReportLLM(), cwd=tmp_path, tools=_tools())
    res = await node.run(NodeContext(_state(), cancel=asyncio.Event()))
    er = res.output
    assert isinstance(er, EnvReport)
    assert er.ready is False
    assert er.install_steps == tuple(plan_commands(tmp_path))
