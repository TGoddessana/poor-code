"""SlashCommand — client-side commands that bypass the LLM.

A SlashCommand owns a verb (`/login`, `/help`, …) and declares its argument
shape so the parser can split tokens vs preserve raw natural-language text,
and so the autocomplete UI can render a usage hint.

SlashContext is the narrow surface the app exposes to commands so commands
don't need to import the full App class.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable


class ArgKind(Enum):
    TOKEN = "token"   # one whitespace-delimited token
    REST = "rest"     # entire remainder of line, raw (for natural language)


@dataclass(frozen=True)
class Arg:
    name: str
    kind: ArgKind
    optional: bool = False


@dataclass(frozen=True)
class ParsedArgs:
    values: dict[str, str]
    raw: str


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
    args: tuple[Arg, ...]

    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None: ...


def usage_hint(cmd: SlashCommand) -> str:
    parts = [f"/{cmd.name}"]
    for a in cmd.args:
        parts.append(f"[{a.name}]" if a.optional else f"<{a.name}>")
    return " ".join(parts)
