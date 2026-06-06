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


# Credential env vars forwarded into the container if present on the bench host.
_KEY_ENVS = ("OLLAMA_API_KEY", "OPENAI_API_KEY", "POOR_CODE_API_KEY")


def build_env() -> dict[str, str]:
    """Credentials passed into the container. POOR_CODE_MODEL is always required;
    at least one provider key must be present. POOR_CODE_PROVIDER (default
    ollama_cloud, resolved container-side) selects which provider to build."""
    env = {"POOR_CODE_MODEL": os.environ["POOR_CODE_MODEL"]}
    provider = os.environ.get("POOR_CODE_PROVIDER")
    if provider:
        env["POOR_CODE_PROVIDER"] = provider
    # Let the host pick which branch/tag/commit and repo install.sh installs in the
    # container. install.sh reads these from the container env (defaulting to main);
    # without forwarding them here, a host-side override silently has no effect.
    for opt in ("POOR_CODE_GIT_REF", "POOR_CODE_GIT_URL"):
        val = os.environ.get(opt)
        if val:
            env[opt] = val
    keys = {k: os.environ[k] for k in _KEY_ENVS if os.environ.get(k)}
    if not keys:
        raise KeyError(
            "no provider credential: set OLLAMA_API_KEY, or OPENAI_API_KEY "
            "(with POOR_CODE_PROVIDER=openai), or POOR_CODE_API_KEY")
    env.update(keys)
    return env


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
                TerminalCommand(command=cmd, max_timeout_sec=1800.0, block=True)
                for cmd in build_run_commands(instruction)
            ]
except ImportError:  # terminal-bench not installed — builders still usable/testable
    PoorCodeAgent = None  # type: ignore[assignment]
