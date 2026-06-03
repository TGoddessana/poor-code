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


# --- cwd containment helpers (shared by read-only tools) ----------------------

def resolve_within_cwd(cwd: Path, path: str) -> Path:
    """Resolve `path` against `cwd` and refuse anything that escapes it.
    `.resolve()` normalizes '..' so this rejects parent-escaping paths."""
    raw = Path(path)
    target = (cwd / raw).resolve() if not raw.is_absolute() else raw.resolve()
    cwd_resolved = cwd.resolve()
    if cwd_resolved != target and cwd_resolved not in target.parents:
        raise PermissionError(f"path outside cwd: {path}")
    return target


def reject_escaping_glob(pattern: str) -> None:
    """Refuse glob patterns that leave the working dir. A '../**/*' pattern made
    grep walk the whole container filesystem (OOM); an absolute '/**' pattern is
    likewise out of scope."""
    p = pattern.strip()
    if not p:
        return
    if p.startswith("/") or Path(p).is_absolute():
        raise ValueError(f"absolute glob not allowed: {pattern}")
    if ".." in Path(p).parts:
        raise ValueError(f"glob may not escape the working dir with '..': {pattern}")
