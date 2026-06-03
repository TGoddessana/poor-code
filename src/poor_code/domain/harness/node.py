"""Node abstraction. A node is a thin worker: reads state, returns a NodeResult.
It never writes to the store and never decides the next hop (route() does)."""
from __future__ import annotations

import asyncio
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


MAX_DISPATCH_ATTEMPTS = 3


def _retry_nudge(err: StructuredOutputError) -> str:
    """Corrective message fed back to the model to re-roll a failed dispatch.
    Same principle as feeding tool errors back in the explore loop — not text
    recovery, but giving the model another, better-informed attempt."""
    return (
        f"Your previous reply was not accepted: {err.detail}. Respond again by "
        "calling the required tool exactly once with arguments that satisfy its "
        "JSON schema. Output only the tool call — no prose, no code fences."
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

    def output_model(self) -> type[BaseModel] | None:
        """The pydantic model backing the output tool. When provided, _dispatch
        validates every attempt against it and re-rolls on schema failure. None
        (default) → only re-rolls when the model produces no tool call at all."""
        return None

    def parse(self, args_json: str) -> object:
        raise NotImplementedError

    # --- dispatch ---
    async def run(self, ctx: NodeContext) -> NodeResult:
        args_json = await self._dispatch(ctx)
        return NodeResult(output=self.parse(args_json))

    async def _dispatch(self, ctx: NodeContext, extra_messages: list[dict] | None = None) -> str:
        """Stream one forced output-tool call, retrying up to MAX_DISPATCH_ATTEMPTS
        times. Each failure (no tool call, or schema-invalid args when output_model
        is set) is fed back to the model as a corrective message and re-rolled.
        After the budget is exhausted the last StructuredOutputError propagates."""
        base = self.build_messages(ctx.state)
        model_cls = self.output_model()
        corrections: list[dict] = []
        last_err: StructuredOutputError | None = None
        for _ in range(MAX_DISPATCH_ATTEMPTS):
            extras = [*(extra_messages or []), *corrections]
            messages = [base[0], *extras, *base[1:]] if extras else base
            try:
                raw = await self._stream_once(ctx, messages)
                if model_cls is not None:
                    validate_output(model_cls, raw, node=self.name)
                return raw
            except StructuredOutputError as e:
                last_err = e
                corrections = [{"role": "user", "content": _retry_nudge(e)}]
        assert last_err is not None
        raise last_err

    async def _stream_once(self, ctx: NodeContext, messages: list[dict]) -> str:
        tools = [self.output_tool()]
        args_by_call: dict[str, str] = {}
        order: list[str] = []
        content: list[str] = []
        async for ev in self._llm.stream(messages=messages, tools=tools):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            match ev:
                case TextDelta(text=t):
                    content.append(t)  # streamed to the sink; also the error payload
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
        raise StructuredOutputError(
            self.name, "".join(content),
            "model produced no tool call (replied with prose or nothing)")
