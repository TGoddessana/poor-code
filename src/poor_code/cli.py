"""poor-code entrypoint.

Builds the app with whatever credentials are saved on disk. If none, the agent
starts with a NoAuthLLM stub that fails the first turn with a hint to /login.
"""
from __future__ import annotations

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra import auth_store
from poor_code.infra.context_loader import ContextLoader
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.settings import SettingsLoader
from poor_code.infra.system_prompt import SystemPromptComposer
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.provider.providers import ollama_cloud
from poor_code.slash.commands.login import LoginCommand
from poor_code.slash.registry import SlashRegistry


class NoAuthLLM:
    """Placeholder LLM used until the user runs /login.

    Raises on stream() so the Agent's exception handler emits a TurnFailed
    with a message that points the user at the right command.
    """

    async def stream(self, messages, tools):  # type: ignore[no-untyped-def]
        raise RuntimeError("no provider configured — type /login to set one up")
        yield  # pragma: no cover — unreachable, makes this an async generator


def _initial_llm():
    creds = auth_store.get("ollama_cloud")
    if creds and creds.get("api_key") and creds.get("model"):
        return ollama_cloud.client(model=creds["model"], api_key=creds["api_key"])
    return NoAuthLLM()


def _build_assembler() -> TurnAssembler:
    return TurnAssembler(
        settings_loader=SettingsLoader(),
        context_loader=ContextLoader(),
        prompt_composer=SystemPromptComposer(),
        prompt_builder=PromptBuilder(),
    )


def _build_agent() -> Agent:
    return Agent(
        llm=_initial_llm(),
        tools=ToolRegistry([ReadTool()]),
        assembler=_build_assembler(),
    )


def main() -> None:
    agent = _build_agent()
    slash = SlashRegistry([LoginCommand()])
    PoorCodeApp(agent=agent, slash=slash).run()
