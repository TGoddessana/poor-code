"""terminal-bench / harbor adapter for poor-code.

Runs poor-code headless inside the task container. Pure-stdlib command/env builders
(build_run_commands / build_env) are unit-tested without terminal-bench installed.
The PoorCodeAgent class only materializes when terminal_bench is importable.

Smoke (needs Docker + `uv tool install terminal-bench`):
    tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent --task-id hello-world
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

AGENT_NAME = "poor-code"
_INSTALL_SCRIPT = Path(__file__).resolve().parent / "install.sh"


def build_run_commands(instruction: str) -> list[str]:
    """Command(s) the harness runs in the container to drive poor-code on a task."""
    return [f"poor-code --headless {shlex.quote(instruction)}"]


def build_env() -> dict[str, str]:
    """Credentials passed into the container. Both required on the bench host."""
    return {
        "OLLAMA_API_KEY": os.environ["OLLAMA_API_KEY"],
        "POOR_CODE_MODEL": os.environ["POOR_CODE_MODEL"],
    }


try:  # only define the real agent when terminal-bench is present
    from terminal_bench.agents.installed_agents.abstract_installed_agent import (
        AbstractInstalledAgent,
    )
    from terminal_bench.terminal.models import TerminalCommand

    class PoorCodeAgent(AbstractInstalledAgent):
        @staticmethod
        def name() -> str:
            return AGENT_NAME

        @property
        def _env(self) -> dict[str, str]:
            return build_env()

        @property
        def _install_agent_script_path(self) -> Path:
            return _INSTALL_SCRIPT

        def _run_agent_commands(self, instruction: str) -> list[TerminalCommand]:
            # build_run_commands stays pure str (unit-testable without tb); the
            # tb harness consumes TerminalCommand objects, so wrap here. block=True
            # makes the harness wait for `poor-code --headless` to exit before tests run.
            return [
                TerminalCommand(command=cmd, max_timeout_sec=600.0, block=True)
                for cmd in build_run_commands(instruction)
            ]
except ImportError:  # terminal-bench not installed — builders still usable/testable
    PoorCodeAgent = None  # type: ignore[assignment]
