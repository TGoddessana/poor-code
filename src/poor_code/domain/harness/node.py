"""Node abstraction. A node is a thin worker: reads state, returns a NodeResult.
It never writes to the store and never decides the next hop (route() does)."""
from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, TypeVar, Union, get_args, get_origin, runtime_checkable

from pydantic import BaseModel, ValidationError

from poor_code.domain.harness.steering import driver_feedback_message, steering_message
from poor_code.domain.session.models import (
    Layer, Phase, Query, SessionState, TriggerKind, Verdict, VerdictKind,
)
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)
from poor_code.provider.usage import tag


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


def strip_code_fence(text: str) -> str:
    """Normalize a structured-output payload that arrived as text. A weak model often
    replies with ```json {...} ``` (or with leading prose) instead of via the tool
    channel; the wrapper breaks JSON parsing at column 1. Drop a wrapping markdown
    fence, then slice to the outermost balanced braces. This is transport
    normalization, NOT schema relaxation — the result is still schema-validated."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        return s[start:end + 1]
    return s


def _list_item_type(annotation: Any) -> type | None:
    """If `annotation` denotes a list (incl. Optional[list[...]]), return its item
    type (the inner pydantic model, when it is one), else None for non-list fields."""
    origin = get_origin(annotation)
    if origin in (list, tuple):
        args = get_args(annotation)
        return args[0] if args else None
    if origin is Union:  # Optional[list[X]] / list[X] | None
        for arg in get_args(annotation):
            if get_origin(arg) in (list, tuple):
                args = get_args(arg)
                return args[0] if args else type(None)
    return None


def _looks_like_item(val: Any, item_t: type | None) -> bool:
    """True when `val` is itself one item of the list (its keys belong to the item
    model) rather than a `{wrapper_key: ...}` envelope around the list."""
    if isinstance(val, dict) and isinstance(item_t, type) and issubclass(item_t, BaseModel):
        return bool(val) and set(val).issubset(set(item_t.model_fields))
    return False


def _as_list(val: Any, item_t: type | None) -> list:
    """Coerce a value emitted where a list was expected into a list.
    A bare item object -> a one-element list; `{wrapper: [...]}` -> the inner list
    (the documented weak-model deformation); `{wrapper: obj}` -> [obj]; scalar -> [scalar]."""
    if isinstance(val, list):
        return val
    if _looks_like_item(val, item_t):
        return [val]
    if isinstance(val, dict):
        if len(val) == 1:
            inner = next(iter(val.values()))
            return inner if isinstance(inner, list) else [inner]
        return [val]
    return [val]


def coerce_to_schema(data: Any, model: type[BaseModel]) -> Any:
    """Deterministically repair the SHAPE of weak-model output to match `model`,
    recursively. Only list-typed fields are reshaped (the failure class Ollama
    Cloud produces without constrained decoding); everything else is left for
    validation to accept or reject. Idempotent on already-correct data."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    for name, field in model.model_fields.items():
        if name not in out or out[name] is None:
            continue  # None is valid for an Optional field — don't wrap it as [None]
        item_t = _list_item_type(field.annotation)
        if item_t is not None:
            items = _as_list(out[name], item_t)
            if isinstance(item_t, type) and issubclass(item_t, BaseModel):
                items = [coerce_to_schema(v, item_t) for v in items]
            out[name] = items
        elif isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            out[name] = coerce_to_schema(out[name], field.annotation)
    return out


def validate_output(model_cls: type[_M], raw: str, *, node: str) -> _M:
    """Validate a node's structured-output JSON against its schema, re-raising
    any failure as StructuredOutputError with the raw payload attached. The payload
    is first SHAPE-coerced (coerce_to_schema) so the common weak-model deformation
    (a list emitted as a singular-key object) validates instead of crashing."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise StructuredOutputError(node, raw, f"not valid JSON: {e}") from e
    try:
        return model_cls.model_validate(coerce_to_schema(data, model_cls))
    except ValidationError as e:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in e.errors()
        )
        raise StructuredOutputError(node, raw, detail) from e


MAX_DISPATCH_ATTEMPTS = 3


def _stub_for(schema: dict[str, Any]) -> Any:
    """A type-appropriate placeholder for a JSON-schema node (a weak model follows an
    example far better than a bare schema)."""
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        props = schema.get("properties", {})
        required = schema.get("required") or list(props)
        return {k: _stub_for(props[k]) for k in required if k in props}
    if t == "array":
        items = schema.get("items")
        return [_stub_for(items)] if isinstance(items, dict) and items else []
    if t == "string":
        return "..."
    if t in ("integer", "number"):
        return 0
    if t == "boolean":
        return False
    for key in ("anyOf", "oneOf"):
        for sub in schema.get(key, []):
            if isinstance(sub, dict) and sub.get("type") != "null":
                return _stub_for(sub)
    return None


def _example_from_schema(schema: dict[str, Any]) -> str:
    return json.dumps(_stub_for(schema), ensure_ascii=False)


def _retry_nudge(
    err: StructuredOutputError,
    *,
    schema: dict[str, Any] | None = None,
    example: str | None = None,
) -> str:
    """Corrective message fed back to the model to re-roll a failed dispatch. A weak
    model repeats a schema mistake unless it sees (a) its own rejected output, (b) the
    exact schema, and (c) a minimal valid example — same principle as the interviewer's
    prev_raw resend, promoted to the common path so every node benefits."""
    parts = [f"Your previous reply was not accepted: {err.detail}."]
    if err.raw:
        clip = err.raw if len(err.raw) <= 600 else err.raw[:600] + " …[truncated]"
        parts.append(f"\n\nYour previous output (rejected — do NOT repeat this shape):\n{clip}")
    if schema is not None:
        parts.append("\n\nThe tool arguments MUST satisfy this JSON schema:\n"
                     f"{json.dumps(schema, ensure_ascii=False)}")
    if example is not None:
        parts.append(f"\n\nA minimal valid example:\n{example}")
    parts.append("\n\nRespond again by calling the required tool exactly once with "
                 "arguments that satisfy the schema. Output only the tool call — no "
                 "prose, no code fences.")
    return "".join(parts)


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
    runtime: Any = None


@runtime_checkable
class StateUpdate(Protocol):
    def apply_to(self, s: "SessionState") -> "SessionState": ...


@runtime_checkable
class Node(Protocol):
    name: str
    async def run(self, ctx: NodeContext) -> NodeResult: ...


# layer → the history-logged node a repair bounce targets, used by the default
# repair-bounce counter. Close to route._SHALLOWEST but NOT identical: this counts the
# node that actually appears in history (e.g. "implementer"), whereas route's back-edge
# may target a wrapping subgraph ("implement_loop"). Kept here so GateNode is self-contained.
_SHALLOWEST_FOR_COUNTING = {
    Layer.IMPLEMENTATION: "implementer",
    Layer.PLAN: "planner",
    Layer.UNDERSTANDING: "explorer",
    Layer.ACCEPTANCE: "acceptance_oracle",
}


class GateNode(ABC):
    """결정론 게이트의 공통 골격. check()==None → ADVANCE; 실패 시 repair 예산 내면
    REPAIR(layer, hint), 예산 초과면 ESCALATE. repair 바운스 횟수는 history 에서 센다.
    개별 게이트가 카운트 규칙이 다르면 _repair_count 를 오버라이드한다."""
    name: str
    layer: Layer
    repair_budget: int
    phase: Phase  # every gate declares its cursor phase (read by the Driver)
    # Experiment toggle: a gate marked advisable may be demoted to NON-BLOCKING when
    # POOR_CODE_ADVISORY_GATES is set — it surfaces its objection to the trace but lets
    # work flow on (only the implementer's real validation floor binds). Tests the
    # hypothesis that the planning-layer gate BOUNCES (not the checks) are the bottleneck.
    advisable: bool = False

    @abstractmethod
    def check(self, state: SessionState) -> str | None:
        """None → 통과(ADVANCE). 문자열 → 실패 사유(hint)."""
        ...

    def _advisory_mode(self) -> bool:
        return self.advisable and os.environ.get(
            "POOR_CODE_ADVISORY_GATES", "").strip().lower() in ("1", "true", "yes", "on")

    async def run(self, ctx: NodeContext) -> NodeResult:
        hint = self.check(ctx.state)
        if hint is None:
            return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
        if self._advisory_mode():
            # Do NOT bounce: the plan/spec flows on; the objection is advisory only.
            sink = getattr(ctx, "sink", None)
            if sink is not None and hasattr(sink, "node_repaired"):
                sink.node_repaired(self.name, f"advisory (not enforced): {hint}")
            return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE, hint=hint))
        if self._repair_count(ctx.state) >= self.repair_budget:
            return NodeResult(verdict=Verdict(
                kind=VerdictKind.ESCALATE, query=self.escalate_query(hint)))
        return NodeResult(verdict=Verdict(
            kind=VerdictKind.REPAIR, layer=self.layer, hint=hint))

    def escalate_query(self, hint: str) -> str:
        """ESCALATE 시 사용자에게 보일 메시지. 기본은 실패 hint 그대로.
        게이트별로 접두 문구가 다르면 오버라이드한다."""
        return hint

    def _repair_count(self, state: SessionState) -> int:
        target = _SHALLOWEST_FOR_COUNTING.get(self.layer)
        return sum(1 for t in state.history
                   if t.trigger is TriggerKind.GATE and t.to_node == target)


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

    def _response_format(self) -> dict[str, Any]:
        """Force schema-valid JSON output via response_format. The provider only
        attaches it when the route declares the capability (e.g. ollama_cloud);
        otherwise it is dropped and tool-calling remains the channel. The schema
        is the output tool's already-inlined parameters, so a model that would
        otherwise reply with prose is constrained to emit the structured object —
        which then arrives as message content rather than a tool call."""
        fn = self.output_tool()["function"]
        return {"type": "json_schema",
                "json_schema": {"name": fn["name"], "schema": fn.get("parameters", {})}}

    async def _dispatch(self, ctx: NodeContext, extra_messages: list[dict] | None = None) -> str:
        """Stream one forced structured output, retrying up to MAX_DISPATCH_ATTEMPTS
        times. The output may arrive as a tool call OR (under response_format) as
        JSON content; either way it is validated when output_model is set. Each
        failure (no output, or schema-invalid) is fed back as a corrective message
        and re-rolled. After the budget is exhausted the last error propagates."""
        base = self.build_messages(ctx.state)
        _sm = steering_message(getattr(ctx.state, "steering_notes", None) or ())
        _fm = driver_feedback_message(ctx.state, self.name)
        steer_msgs: list[dict] = [m for m in (_sm, _fm) if m is not None]
        if ctx.sink is not None:
            phase = ctx.state.cursor.phase.value if ctx.state.cursor else ""
            ctx.sink.node_context(self.name, phase, base)
        model_cls = self.output_model()
        response_format = self._response_format()
        _schema = self.output_tool().get("function", {}).get("parameters")
        _example = _example_from_schema(_schema) if _schema else None
        corrections: list[dict] = []
        last_err: StructuredOutputError | None = None
        for _ in range(MAX_DISPATCH_ATTEMPTS):
            extras = [*steer_msgs, *(extra_messages or []), *corrections]
            messages = [base[0], *extras, *base[1:]] if extras else base
            try:
                raw = strip_code_fence(await self._stream_once(ctx, messages, response_format))
                if model_cls is not None:
                    validate_output(model_cls, raw, node=self.name)
                if ctx.sink is not None:
                    ctx.sink.node_raw_output(self.name, raw)
                return raw
            except StructuredOutputError as e:
                last_err = e
                corrections = [{"role": "user",
                                "content": _retry_nudge(e, schema=_schema, example=_example)}]
        assert last_err is not None
        raise last_err

    async def _stream_once(
        self, ctx: NodeContext, messages: list[dict],
        response_format: dict[str, Any] | None = None,
    ) -> str:
        tools = [self.output_tool()]
        tag(self._llm, self.name)   # attribute this call's tokens to this node
        args_by_call: dict[str, str] = {}
        order: list[str] = []
        content: list[str] = []
        async for ev in self._llm.stream(
            messages=messages, tools=tools, response_format=response_format,
        ):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            match ev:
                case TextDelta(text=t):
                    content.append(t)  # streamed to the sink; also the error payload
                    if ctx.sink is not None:
                        ctx.sink.node_thinking_delta(self.name, t)
                case ToolCallStarted(call_id=cid):
                    args_by_call[cid] = ""
                    order.append(cid)
                case ToolCallInputDelta(call_id=cid, json_delta=d):
                    if cid in args_by_call:
                        args_by_call[cid] += d
                    if ctx.sink is not None:
                        ctx.sink.node_thinking_delta(self.name, d)
                case ToolCallEnded() | FinishedReason():
                    pass
        if order:
            return args_by_call[order[0]] or "{}"
        # No tool call: under response_format the structured object arrives as
        # content. Accept it only when there is an output_model to validate it
        # against (the caller validates) — otherwise prose could slip through.
        text = "".join(content)
        if text.strip() and self.output_model() is not None:
            return text
        raise StructuredOutputError(
            self.name, text,
            "model produced no tool call (replied with prose or nothing)")
