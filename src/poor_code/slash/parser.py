"""Parse `/name args…` text into (name, ParsedArgs) using a command's arg schema.

REST args grab the entire remainder of the line raw; TOKEN args take one
whitespace-delimited token. Whitespace between tokens is collapsed.
"""
from __future__ import annotations

from poor_code.slash.base import Arg, ArgKind, ParsedArgs, SlashCommand
from poor_code.slash.registry import SlashRegistry


class UnknownCommand(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class MissingArg(Exception):
    def __init__(self, cmd: SlashCommand, arg: Arg) -> None:
        super().__init__(arg.name)
        self.cmd = cmd
        self.arg = arg


def parse(text: str, registry: SlashRegistry) -> tuple[str, ParsedArgs]:
    assert text.startswith("/")
    head, _, rest = text[1:].partition(" ")
    name = head
    cmd = registry.get(name)
    if cmd is None:
        raise UnknownCommand(name)
    rest = rest.strip()
    raw = rest
    values: dict[str, str] = {}
    for arg in cmd.args:
        if arg.kind is ArgKind.REST:
            values[arg.name] = rest
            rest = ""
            break  # REST is validated last by SlashRegistry
        # TOKEN
        token, _, rest = rest.partition(" ")
        rest = rest.lstrip()
        if not token:
            if arg.optional:
                values[arg.name] = ""
                continue
            raise MissingArg(cmd, arg)
        values[arg.name] = token
    return name, ParsedArgs(values=values, raw=raw)
