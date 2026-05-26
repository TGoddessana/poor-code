"""/exit — quit the application."""
from __future__ import annotations

from dataclasses import dataclass, field

from poor_code.slash.base import Arg, ParsedArgs, SlashContext


@dataclass
class ExitCommand:
    name: str = "exit"
    description: str = "Quit the application"
    args: tuple[Arg, ...] = field(default_factory=tuple)

    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None:
        ctx.exit()