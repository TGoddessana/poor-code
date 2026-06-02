"""Node abstraction. A node is a thin worker: reads state, returns a NodeResult.
It never writes to the store and never decides the next hop (route() does)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from poor_code.domain.session.models import Query, SessionState, Verdict
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)


@dataclass(frozen=True)
class NodeResult:
    output: object | None = None
    verdict: Verdict | None = None
    query: Query | None = None
    branch: str | None = None


@dataclass
class NodeContext:
    state: SessionState
    cancel: asyncio.Event
    sink: Any = None


@runtime_checkable
class Node(Protocol):
    name: str
    async def run(self, ctx: NodeContext) -> NodeResult: ...


@runtime_checkable
class _LLMClientLike(Protocol):
    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]: ...


class AgentNode:
    """Base for agent (LLM) nodes. Structured output = a single forced 'output tool'
    whose JSON schema is the node's output object. Subclasses provide messages,
    the tool schema, and parse(args_json) -> output object."""

    name: str

    def __init__(self, llm: _LLMClientLike) -> None:
        self._llm = llm

    # --- subclass hooks ---
    def build_messages(self, state: SessionState) -> list[dict[str, Any]]:
        raise NotImplementedError

    def output_tool(self) -> dict[str, Any]:
        raise NotImplementedError

    def parse(self, args_json: str) -> object:
        raise NotImplementedError

    # --- dispatch ---
    async def run(self, ctx: NodeContext) -> NodeResult:
        args_json = await self._dispatch(ctx)
        return NodeResult(output=self.parse(args_json))

    async def _dispatch(self, ctx: NodeContext, extra_messages: list[dict] | None = None) -> str:
        base = self.build_messages(ctx.state)
        if extra_messages:
            messages = [base[0], *extra_messages, *base[1:]]
        else:
            messages = base
        tools = [self.output_tool()]
        args_by_call: dict[str, str] = {}
        order: list[str] = []
        async for ev in self._llm.stream(messages=messages, tools=tools):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            match ev:
                case TextDelta(text=t):
                    if ctx.sink is not None:
                        ctx.sink.text_delta(t)
                case ToolCallStarted(call_id=cid):
                    args_by_call[cid] = ""
                    order.append(cid)
                case ToolCallInputDelta(call_id=cid, json_delta=d):
                    if cid in args_by_call:
                        args_by_call[cid] += d
                case ToolCallEnded() | FinishedReason():
                    pass
        if not order:
            raise ValueError(f"{self.name}: model produced no structured output")
        return args_by_call[order[0]] or "{}"
