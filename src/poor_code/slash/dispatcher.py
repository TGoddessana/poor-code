"""SlashDispatcher — try-handle pipeline for slash text.

Owns parse → execute → notify-on-error. Lets App.submit stay focused on
input dispatch + agent turn lifecycle.
"""
from __future__ import annotations

from poor_code.slash.base import SlashContext, usage_hint
from poor_code.slash.parser import MissingArg, UnknownCommand, parse
from poor_code.slash.registry import SlashRegistry


class SlashDispatcher:
    def __init__(self, registry: SlashRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> SlashRegistry:
        return self._registry

    def dispatch(self, text: str, ctx: SlashContext) -> bool:
        """Try to handle text as a slash command.
        Returns True if handled (executed or user-visible error)."""
        if not text.startswith("/"):
            return False
        try:
            name, parsed = parse(text, self._registry)
        except UnknownCommand as e:
            ctx.notify(f"unknown command: /{e.name}", severity="warning")
            return True
        except MissingArg as e:
            ctx.notify(
                f"missing arg: {e.arg.name} — usage: {usage_hint(e.cmd)}",
                severity="warning",
            )
            return True
        self._registry.get(name).execute(ctx, parsed)
        return True
