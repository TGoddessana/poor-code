"""Tool abstraction — mirror of opencode's Tool.Def in Python.

A Tool exposes a name+description, a pydantic params model (which becomes
the JSON schema sent to the LLM), and an async execute() that receives the
parsed args plus a ToolContext (cancel signal, cwd, permission ask hook).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass
class ExecuteResult:
    title: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionRequest:
    tool_id: str
    pattern: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    turn_id: str
    cancel: asyncio.Event
    cwd: Path
    ask: Callable[[PermissionRequest], Awaitable[Literal["allow", "deny"]]]


@runtime_checkable
class Tool(Protocol):
    id: str
    description: str
    params: type[BaseModel]

    async def execute(self, args: BaseModel, ctx: ToolContext) -> ExecuteResult: ...


async def allow_all(_: PermissionRequest) -> Literal["allow", "deny"]:
    """Stub `ask` implementation for first-stage. ReadTool doesn't call ask,
    but the Context still requires a callable. Replace with a real prompt
    when the permission UI lands.
    """
    return "allow"
