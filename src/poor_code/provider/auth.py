from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class MissingApiKey(RuntimeError):
    def __init__(self, var: str) -> None:
        super().__init__(f"environment variable {var!r} is not set")
        self.var = var


@runtime_checkable
class Auth(Protocol):
    def apply(self, headers: dict[str, str]) -> None: ...


@dataclass(frozen=True)
class BearerAuth:
    token: str

    @classmethod
    def from_env(cls, var: str) -> "BearerAuth":
        token = os.environ.get(var)
        if not token:
            raise MissingApiKey(var)
        return cls(token)

    def apply(self, headers: dict[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self.token}"
