"""Node abstraction. A node is a thin worker: reads state, returns a NodeResult.
It never writes to the store and never decides the next hop (route() does)."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

from poor_code.domain.session.models import Query, SessionState, Verdict
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)


_M = TypeVar("_M", bound=BaseModel)


class StructuredOutputError(ValueError):
    """A node's LLM returned structured output that failed schema validation.

    Carries the *full* raw payload (Pydantic's own message truncates it) so the
    offending model output is visible in the failed-turn error and in tests."""

    def __init__(self, node: str, raw: str, detail: str) -> None:
        self.node = node
        self.raw = raw
        self.detail = detail
        super().__init__(
            f"{node}: invalid structured output ({detail}).\n"
            f"raw payload:\n{raw}"
        )


def validate_output(model_cls: type[_M], raw: str, *, node: str) -> _M:
    """Validate a node's structured-output JSON against its schema, re-raising
    any failure as StructuredOutputError with the raw payload attached."""
    try:
        return model_cls.model_validate_json(raw)
    except ValidationError as e:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in e.errors()
        )
        raise StructuredOutputError(node, raw, detail) from e


_CODE_FENCE = re.compile(r"```[a-zA-Z0-9_]*\s*\n?(.*?)```", re.DOTALL)


def _extract_json_payload(text: str) -> str:
    """Recover the structured payload from free-text model output.

    Some Ollama models/templates emit the forced tool call as text instead of
    via the tool_calls channel — wrapped in a ```json / ```tool_call fence,
    and sometimes as a {"name": ..., "arguments": {...}} envelope. Strip the
    fence and unwrap the envelope down to the bare arguments object so the
    schema validator sees what it expects."""
    s = text.strip()
    if not s:
        return ""
    m = _CODE_FENCE.search(s)
    if m:
        s = m.group(1).strip()
    try:
        obj = json.loads(s)
    except (ValueError, TypeError):
        return s  # not parseable here — let validate_output surface the raw text
    if (isinstance(obj, dict) and "arguments" in obj
            and isinstance(obj["arguments"], (dict, list))):
        return json.dumps(obj["arguments"])
    return s


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
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
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
        content: list[str] = []
        async for ev in self._llm.stream(messages=messages, tools=tools):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            match ev:
                case TextDelta(text=t):
                    content.append(t)  # kept for the rendered-as-text fallback
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
        if order:
            return args_by_call[order[0]] or "{}"
        # Some Ollama models/templates render the forced tool call as fenced text
        # in the message content instead of using the tool_calls channel; recover
        # the payload from there before giving up.
        payload = _extract_json_payload("".join(content))
        if payload:
            return payload
        raise ValueError(f"{self.name}: model produced no structured output")
