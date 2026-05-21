"""Test doubles for infra components."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from poor_code.infra.context_loader import LoadedContext
from poor_code.infra.settings import Settings
from poor_code.infra.system_prompt import SystemPrompt


@dataclass
class FakeGit:
    is_repo_value: bool = True
    status_value: str = ""
    branch_value: str = "main"
    commits_value: str = ""
    timeouts: bool = False

    async def is_repo(self, cwd: Path) -> bool:
        return self.is_repo_value

    async def status(self, cwd: Path) -> str:
        return "" if self.timeouts else self.status_value

    async def branch(self, cwd: Path) -> str:
        return "" if self.timeouts else self.branch_value

    async def recent_commits(self, cwd: Path, n: int) -> str:
        return "" if self.timeouts else self.commits_value


@dataclass
class FakeSettingsLoader:
    effective: dict[str, Any] = field(default_factory=dict)
    sources: tuple[Path, ...] = ()

    async def load(self, cwd: Path) -> Settings:
        return Settings(sources=self.sources, effective=dict(self.effective))


@dataclass
class FakeContextLoader:
    user_block: str = ""
    system_block: str = ""
    sources: tuple[Path, ...] = ()

    async def load(self, cwd: Path) -> LoadedContext:
        return LoadedContext(
            user_block=self.user_block,
            system_block=self.system_block,
            sources=self.sources,
        )


@dataclass
class FakeSystemPromptComposer:
    text: str = "SYS"
    static: str = ""
    dynamic: str = ""

    def compose(self, settings: Settings, cwd: Path) -> SystemPrompt:
        return SystemPrompt(text=self.text, static=self.static, dynamic=self.dynamic)


@dataclass
class FakeTurnAssembler:
    messages: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def build(
        self, history: list[dict[str, Any]], cwd: Path
    ) -> list[dict[str, Any]]:
        self.calls.append({"history": list(history), "cwd": cwd})
        if self.messages:
            return list(self.messages)
        return [{"role": "system", "content": "fake-sys"}, *history]
