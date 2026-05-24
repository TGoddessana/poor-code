from __future__ import annotations

from poor_code.slash.base import ArgKind, SlashCommand


class DuplicateSlashName(ValueError):
    pass


class SlashRegistry:
    def __init__(self, commands: list[SlashCommand]) -> None:
        by_name: dict[str, SlashCommand] = {}
        for c in commands:
            if c.name in by_name:
                raise DuplicateSlashName(c.name)
            self._validate_args(c)
            by_name[c.name] = c
        self._by_name = by_name

    @staticmethod
    def _validate_args(cmd: SlashCommand) -> None:
        args = getattr(cmd, "args", ())
        for i, a in enumerate(args):
            if a.kind is ArgKind.REST and i != len(args) - 1:
                raise ValueError(
                    f"command /{cmd.name}: REST arg '{a.name}' must be last"
                )

    def get(self, name: str) -> SlashCommand | None:
        return self._by_name.get(name)

    def all(self) -> list[SlashCommand]:
        return list(self._by_name.values())
