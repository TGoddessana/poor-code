from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeSlashContext:
    notifications: list[tuple[str, str]] = field(default_factory=list)
    pushed_screens: list[Any] = field(default_factory=list)
    llms_set: list[Any] = field(default_factory=list)

    def push_screen(self, screen, callback=None):
        self.pushed_screens.append(screen)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((severity, message))

    def set_llm(self, llm) -> None:
        self.llms_set.append(llm)
