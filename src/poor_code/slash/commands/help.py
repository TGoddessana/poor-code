"""/help — list keybindings and commands."""
from __future__ import annotations

from dataclasses import dataclass, field

from poor_code.slash.base import Arg, ParsedArgs, SlashContext

_HELP = (
    "Keys: Ctrl+Q quit · Ctrl+C cancel/quit · Ctrl+I state inspector · "
    "/login configure provider · /state inspect state · /help this help"
)


@dataclass
class HelpCommand:
    name: str = "help"
    description: str = "Show keybindings and commands"
    args: tuple[Arg, ...] = field(default_factory=tuple)

    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None:
        ctx.notify(_HELP)
