"""SlashCommand — client-side commands that bypass the LLM.

A SlashCommand owns a verb (`/login`, `/help`, …) and executes effects on the
running app: opening a modal, mutating the agent, posting a notification, etc.
Anything that should NOT just become a chat message to the model.

SlashContext is the narrow surface the app exposes to commands so commands
don't need to import the full App class.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class SlashContext(Protocol):
    def push_screen(
        self, screen: Any, callback: Callable[[Any], None] | None = None
    ) -> Any: ...
    def notify(self, message: str, *, severity: str = "information") -> None: ...
    def set_llm(self, llm: Any) -> None: ...


@runtime_checkable
class SlashCommand(Protocol):
    name: str
    description: str

    def execute(self, ctx: SlashContext, args: tuple[str, ...]) -> None: ...
