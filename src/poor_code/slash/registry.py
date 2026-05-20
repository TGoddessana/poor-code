from __future__ import annotations

from poor_code.slash.base import SlashCommand


class DuplicateSlashName(ValueError):
    pass


class SlashRegistry:
    def __init__(self, commands: list[SlashCommand]) -> None:
        by_name: dict[str, SlashCommand] = {}
        for c in commands:
            if c.name in by_name:
                raise DuplicateSlashName(c.name)
            by_name[c.name] = c
        self._by_name = by_name

    def get(self, name: str) -> SlashCommand | None:
        return self._by_name.get(name)

    def all(self) -> list[SlashCommand]:
        return list(self._by_name.values())
