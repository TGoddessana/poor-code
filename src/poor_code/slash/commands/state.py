"""/state — open the agent state inspector (also bound to ctrl+i)."""
from __future__ import annotations

from dataclasses import dataclass, field

from poor_code.slash.base import Arg, ParsedArgs, SlashContext
from poor_code.ui.screens.state_inspector import StateInspector


@dataclass
class StateCommand:
    name: str = "state"
    description: str = "Inspect the agent's internal state"
    args: tuple[Arg, ...] = field(default_factory=tuple)

    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None:
        ctx.push_screen(StateInspector())
