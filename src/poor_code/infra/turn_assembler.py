"""TurnAssembler — façade that orchestrates the per-turn message build.

Agent holds exactly one of these. Internally, SettingsLoader → ContextLoader →
SystemPromptComposer → PromptBuilder runs each turn; results flow to LLMClient.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from poor_code.infra.context_loader import LoadedContext
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.settings import Settings
from poor_code.infra.system_prompt import SystemPrompt


class _SettingsLoaderLike(Protocol):
    async def load(self, cwd: Path) -> Settings: ...


class _ContextLoaderLike(Protocol):
    async def load(self, cwd: Path) -> LoadedContext: ...


class _PromptComposerLike(Protocol):
    def compose(self, settings: Settings, cwd: Path) -> SystemPrompt: ...


class TurnAssembler:
    def __init__(
        self,
        settings_loader: _SettingsLoaderLike,
        context_loader: _ContextLoaderLike,
        prompt_composer: _PromptComposerLike,
        prompt_builder: PromptBuilder,
    ) -> None:
        self._settings = settings_loader
        self._context = context_loader
        self._composer = prompt_composer
        self._builder = prompt_builder

    async def build(
        self, history: list[dict[str, Any]], cwd: Path
    ) -> list[dict[str, Any]]:
        settings = await self._settings.load(cwd)
        ctx = await self._context.load(cwd)
        system = self._composer.compose(settings, cwd)
        return self._builder.build(history, ctx, system)
