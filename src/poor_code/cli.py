"""poor-code entrypoint.

Builds the app with whatever credentials are saved on disk. If none, the agent
starts with a NoAuthLLM stub that fails the first turn with a hint to /login.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness import build_default_registry
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.route import route
from poor_code.domain.project_map import ProjectMap, ProjectMapStore
from poor_code.domain.session import SessionService
from poor_code.domain.session.store import SessionStore
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.edit import EditTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.write import WriteTool
from poor_code.infra import auth_store, paths
from poor_code.infra.context_loader import ContextLoader
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.settings import SettingsLoader
from poor_code.infra.system_prompt import SystemPromptComposer
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.domain.project_map import make_default_builder
from poor_code.provider.providers import ollama_cloud
from poor_code.slash.commands.login import LoginCommand
from poor_code.slash.dispatcher import SlashDispatcher
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
        return ollama_cloud.configure(model=creds["model"], api_key=creds["api_key"])
    return NoAuthLLM()


def _build_assembler() -> TurnAssembler:
    return TurnAssembler(
        settings_loader=SettingsLoader(),
        context_loader=ContextLoader(),
        prompt_composer=SystemPromptComposer(),
        prompt_builder=PromptBuilder(),
    )


def _start_session(cwd: Path) -> SessionService:
    service = SessionService(SessionStore(paths.config_dir(cwd)))
    service.start_session(cwd)
    return service


def _build_agent(session: SessionService, llm) -> Agent:
    return Agent(
        llm=llm,
        tools=ToolRegistry([ReadTool(), WriteTool(), EditTool(), BashTool()]),
        assembler=_build_assembler(),
        session=session,
    )


def _build_project_map_builder():
    return make_default_builder()


def _load_project_map(cwd: Path) -> ProjectMap:
    try:
        return ProjectMapStore().read(paths.config_dir(cwd))
    except (FileNotFoundError, ValueError):
        return ProjectMap(version=2, generated_at=datetime.now(UTC),
                          cwd=cwd, files=(), parse_errors=())


def _make_driver_factory(project_map: ProjectMap, session: SessionService):
    def make(llm):
        registry = build_default_registry(
            llm=llm, project_map=project_map, agent=_build_agent(session, llm))
        return Driver(registry, route)
    return make


def main() -> None:
    cwd = Path.cwd()
    session = _start_session(cwd)
    agent = _build_agent(session, _initial_llm())
    slash = SlashDispatcher(SlashRegistry([LoginCommand()]))
    builder = _build_project_map_builder()
    make_driver = _make_driver_factory(_load_project_map(cwd), session)
    PoorCodeApp(
        agent=agent, make_driver=make_driver, slash=slash,
        project_map_builder=builder,
    ).run()
