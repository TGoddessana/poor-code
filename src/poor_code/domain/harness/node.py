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

from pathlib import Path

from poor_code.domain.harness.tool_output import clamp_tool_output
from poor_code.domain.tool.base import ToolContext, allow_all


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


def _safe_args(args_json: str) -> dict:
    """Best-effort parse of a tool call's argument JSON into a dict for sink display.
    A non-dict payload is wrapped as {"_": v}; malformed JSON yields {} — never raises,
    since this only feeds the UI's tool_started event, not execution."""
    try:
        v = json.loads(args_json or "{}")
        return v if isinstance(v, dict) else {"_": v}
    except (ValueError, TypeError):
        return {}


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
READ_LOOP_MAX_ITERATIONS = 6


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


@runtime_checkable
class Completion(Protocol):
    """How an AgentNode finishes: the terminal tool the model calls to signal done,
    the schema to validate its args, and how to turn the validated raw payload into a
    NodeResult. extract() MAY raise StructuredOutputError to reject a schema-valid but
    semantically-incomplete output → the engine (AgentNode._terminal) re-rolls."""
    def terminal_tool(self) -> dict[str, Any]: ...
    def output_model(self) -> type[BaseModel] | None: ...
    def extract(self, raw: str, ctx: "NodeContext | None") -> "NodeResult": ...


class StructuredCompletion:
    """Reproduces today's single-shot terminal behavior: validate against `model`
    (done by the engine), then NodeResult(output=parse(raw))."""
    def __init__(self, *, tool: dict[str, Any], model: type[BaseModel] | None,
                 parse) -> None:
        self._tool, self._model, self._parse = tool, model, parse

    def terminal_tool(self) -> dict[str, Any]:
        return self._tool

    def output_model(self) -> type[BaseModel] | None:
        return self._model

    def extract(self, raw: str, ctx) -> "NodeResult":
        return NodeResult(output=self._parse(raw))


class SideEffectCompletion:
    """A Completion whose result is read from the outside world after a tool loop runs
    (design §3.4): no forced output tool, no schema. `extract` is an async callable
    (ctx) -> NodeResult that inspects side effects (e.g. a shadow-git snapshot diff).
    Used by side-effect nodes (the implementer) that run _tool_loop then extract — it
    does NOT flow through _terminal (which is the structured-output terminal stage)."""
    def __init__(self, *, extract) -> None:
        self._extract = extract

    def terminal_tool(self) -> dict[str, Any]:
        return {}

    def output_model(self) -> type[BaseModel] | None:
        return None

    async def extract_async(self, ctx: "NodeContext | None") -> "NodeResult":
        return await self._extract(ctx)


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
    requires: tuple[type, ...] = ()
    produces: tuple[type, ...] = ()
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


@dataclass
class _LoopRound:
    """One completed tool round, handed to ToolLoopHooks.after_round so a node can
    re-clamp prior rounds, append a nudge, or inspect side effects. `messages` is the
    LIVE transcript (mutating it, e.g. appending a nudge, is intentional)."""
    index: int
    calls: list[tuple[str, str, str]]
    tool_msgs: dict[str, dict]
    full_output: dict[str, str]
    messages: list[dict]


@runtime_checkable
class ToolLoopHooks(Protocol):
    """Per-loop customization for AgentNode._tool_loop. All methods have no-op defaults
    via _DefaultHooks; a node overrides only the axes it needs."""
    def clamp(self, output: str) -> str: ...
    def record(self, name: str, args_json: str, output: str) -> None: ...
    async def before_loop(self) -> None: ...
    async def after_round(self, rnd: "_LoopRound") -> None: ...


class _DefaultHooks:
    """Standard-clamp, no recording, no per-round logic — the explorer/verifier baseline."""
    def clamp(self, output: str) -> str:
        return clamp_tool_output(output)
    def record(self, name: str, args_json: str, output: str) -> None:
        pass
    async def before_loop(self) -> None:
        pass
    async def after_round(self, rnd: "_LoopRound") -> None:
        pass


_DEFAULT_HOOKS = _DefaultHooks()


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
    requires: tuple[type, ...] = ()
    produces: tuple[type, ...] = ()

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

    async def _roll_structured(
        self, ctx: NodeContext, *, tool: dict[str, Any],
        model_cls: "type[BaseModel] | None", extra_messages: list[dict] | None = None,
    ) -> str:
        """Shared structured-output roll: assemble messages (steering + driver feedback +
        caller extras + correction re-rolls), stream one forced tool/JSON output, validate
        against `model_cls` when given, and re-roll up to MAX_DISPATCH_ATTEMPTS on schema
        failure. Returns the accepted raw payload. This is the single reliability core that
        both _dispatch (returns raw) and _terminal (then completion.extract) delegate to."""
        base = self.build_messages(ctx.state)
        _sm = steering_message(getattr(ctx.state, "steering_notes", None) or ())
        _fm = driver_feedback_message(ctx.state, self.name)
        steer_msgs: list[dict] = [m for m in (_sm, _fm) if m is not None]
        if ctx.sink is not None:
            phase = ctx.state.cursor.phase.value if ctx.state.cursor else ""
            ctx.sink.node_context(self.name, phase, base)
        response_format = {"type": "json_schema", "json_schema": {
            "name": tool["function"]["name"],
            "schema": tool["function"].get("parameters", {})}}
        _schema = tool.get("function", {}).get("parameters")
        _example = _example_from_schema(_schema) if _schema else None
        corrections: list[dict] = []
        last_err: StructuredOutputError | None = None
        for _ in range(MAX_DISPATCH_ATTEMPTS):
            extras = [*steer_msgs, *(extra_messages or []), *corrections]
            messages = [base[0], *extras, *base[1:]] if extras else base
            try:
                raw = strip_code_fence(
                    await self._stream_once(ctx, messages, response_format, tool=tool,
                                            accept_text_output=model_cls is not None))
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

    async def _dispatch(self, ctx: NodeContext, extra_messages: list[dict] | None = None) -> str:
        """Stream one forced structured output (tool call or, under response_format, JSON
        content), validated when output_model is set, re-rolling on failure. Thin wrapper
        over the shared _roll_structured using this node's own output hooks."""
        return await self._roll_structured(
            ctx, tool=self.output_tool(), model_cls=self.output_model(),
            extra_messages=extra_messages)

    async def _terminal(
        self, ctx: NodeContext, completion: "Completion",
        extra_messages: list[dict] | None = None,
    ) -> "NodeResult":
        """Single-output terminal stage: roll a structured output via the shared core using
        the Completion's terminal tool/model, then delegate result extraction to it. Re-rolls
        on schema-invalid output (inside _roll_structured) OR a semantic rejection where
        completion.extract() raises StructuredOutputError."""
        last_err: StructuredOutputError | None = None
        nudge: list[dict] = []
        for _ in range(MAX_DISPATCH_ATTEMPTS):
            raw = await self._roll_structured(
                ctx, tool=completion.terminal_tool(), model_cls=completion.output_model(),
                extra_messages=[*(extra_messages or []), *nudge])
            try:
                return completion.extract(raw, ctx)
            except StructuredOutputError as e:
                last_err = e
                _schema = completion.terminal_tool().get("function", {}).get("parameters")
                _example = _example_from_schema(_schema) if _schema else None
                nudge = [{"role": "user",
                          "content": _retry_nudge(e, schema=_schema, example=_example)}]
        assert last_err is not None
        raise last_err

    async def _decide_with_tools(
        self, ctx: NodeContext, completion: "Completion", tools: Any,
        *, max_tool_rounds: int = READ_LOOP_MAX_ITERATIONS,
        cwd: "Path | None" = None, leak_text: bool = True,
    ) -> "NodeResult":
        """Unified read-and-decide loop: offer the node's working `tools` AND the
        completion's terminal tool in ONE tool set every round. A working-tool call is
        executed and fed back (the model grounds itself); a call to the terminal tool ends
        the loop via completion.extract → NodeResult. A schema-invalid or semantically
        incomplete terminal call is nudged and the loop continues, bounded by
        MAX_DISPATCH_ATTEMPTS. This replaces the split read-loop + forced-terminal: a model
        that still wants to read at decision time simply reads, instead of emitting an
        invalid structured output (e.g. a stray grep call) that escalated to a parked turn.
        `tools` may be None (terminal-only — equivalent to a single forced dispatch)."""
        base = self.build_messages(ctx.state)
        _sm = steering_message(getattr(ctx.state, "steering_notes", None) or ())
        _fm = driver_feedback_message(ctx.state, self.name)
        steer = [m for m in (_sm, _fm) if m is not None]
        if ctx.sink is not None:
            phase = ctx.state.cursor.phase.value if ctx.state.cursor else ""
            ctx.sink.node_context(self.name, phase, base)
        terminal = completion.terminal_tool()
        terminal_name = terminal["function"]["name"]
        _schema = terminal.get("function", {}).get("parameters")
        _example = _example_from_schema(_schema) if _schema else None
        schemas = [*(tools.schemas() if tools is not None else []), terminal]
        messages = [base[0], *steer, *base[1:]]
        tool_ctx = ToolContext(turn_id=self.name, cancel=ctx.cancel,
                               cwd=cwd if cwd is not None else Path.cwd(), ask=allow_all)
        last_err: StructuredOutputError | None = None
        attempts = 0   # invalid terminal calls / empty rounds — bounded re-roll budget
        for _ in range(max_tool_rounds + MAX_DISPATCH_ATTEMPTS):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            # pass a copy: the stream may capture the list (test fakes do) while this loop
            # keeps mutating `messages` (appending the assistant turn + tool results).
            text, calls = await self._stream_llm_round(
                ctx, list(messages), schemas, leak_text=leak_text)
            assistant: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                assistant["tool_calls"] = [
                    {"id": cid, "type": "function",
                     "function": {"name": name, "arguments": args or "{}"}}
                    for cid, name, args in calls]
            messages.append(assistant)
            if not calls:
                attempts += 1
                if attempts >= MAX_DISPATCH_ATTEMPTS:
                    raise last_err or StructuredOutputError(
                        self.name, text,
                        f"model produced no tool call; expected {terminal_name}")
                messages.append({"role": "user", "content":
                    f"You must call a tool. Read more with a working tool, or call "
                    f"{terminal_name} to finish. Output only the tool call."})
                continue
            for cid, name, args in calls:
                if name == terminal_name:
                    if ctx.sink is not None:
                        ctx.sink.node_raw_output(self.name, args)
                    try:
                        return completion.extract(args, ctx)
                    except StructuredOutputError as e:
                        last_err = e
                        attempts += 1
                        messages.append({"role": "tool", "tool_call_id": cid,
                            "content": _retry_nudge(e, schema=_schema, example=_example)})
                        continue
                if ctx.sink is not None:
                    ctx.sink.tool_started(cid, name, _safe_args(args))
                output = await self._run_tool(tools, name, args, tool_ctx)
                if ctx.sink is not None:
                    if output.startswith("ERROR:"):
                        ctx.sink.tool_failed(cid, output)
                    else:
                        ctx.sink.tool_finished(cid, output)
                messages.append({"role": "tool", "tool_call_id": cid,
                                 "content": clamp_tool_output(output)})
            if attempts >= MAX_DISPATCH_ATTEMPTS:
                assert last_err is not None
                raise last_err
        raise last_err or StructuredOutputError(
            self.name, "",
            f"did not call {terminal_name} within the round budget")

    async def _stream_once(
        self, ctx: NodeContext, messages: list[dict],
        response_format: dict[str, Any] | None = None,
        tool: dict[str, Any] | None = None,
        accept_text_output: bool | None = None,
    ) -> str:
        tools = [tool if tool is not None else self.output_tool()]
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
        # content. Accept it only when there is a model to validate it against (the
        # caller validates) — otherwise prose could slip through. The effective model
        # is the caller's (a Completion via _terminal supplies its own via
        # accept_text_output); default falls back to the node's output_model().
        text = "".join(content)
        accept = (self.output_model() is not None
                  if accept_text_output is None else accept_text_output)
        if text.strip() and accept:
            return text
        raise StructuredOutputError(
            self.name, text,
            "model produced no tool call (replied with prose or nothing)")

    async def _stream_llm_round(
        self, ctx: NodeContext, messages: list[dict], tools_schemas: list[dict],
        *, leak_text: bool = False,
    ) -> tuple[str, list[tuple[str, str, str]]]:
        """One streamed LLM round that MAY call working tools. Returns (text, calls) with
        calls = [(call_id, name, args_json)]. Unifies the loop nodes' copy-pasted round.
        leak_text=True streams reasoning TextDelta to the sink as node_thinking_delta
        (the interviewer read loop / _stream_tools behavior); False accumulates text only
        (the implementer/explorer/verifier behavior — locked by test_explorer_silent_text)."""
        tag(self._llm, self.name)
        text_parts: list[str] = []
        pending: dict[str, dict[str, str]] = {}
        order: list[str] = []
        async for ev in self._llm.stream(
            messages=messages, tools=tools_schemas, response_format=None,
        ):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            match ev:
                case TextDelta(text=t):
                    text_parts.append(t)
                    if leak_text and ctx.sink is not None:
                        ctx.sink.node_thinking_delta(self.name, t)
                case ToolCallStarted(call_id=cid, name=name):
                    pending[cid] = {"name": name, "args": ""}
                    order.append(cid)
                case ToolCallInputDelta(call_id=cid, json_delta=d):
                    if cid in pending:
                        pending[cid]["args"] += d
                case ToolCallEnded() | FinishedReason():
                    pass
        return "".join(text_parts), [
            (cid, pending[cid]["name"], pending[cid]["args"]) for cid in order]

    async def _stream_tools(
        self, ctx: NodeContext, messages: list[dict], tools_schemas: list[dict],
    ) -> tuple[str, list[tuple[str, str, str]]]:
        """Back-compat shim: a leaking round (interviewer read loop). Delegates to the
        unified _stream_round(leak_text=True)."""
        return await self._stream_llm_round(ctx, messages, tools_schemas, leak_text=True)

    async def _run_tool(self, tools: Any, name: str, args_json: str, tool_ctx: Any) -> str:
        tool = tools.get(name)
        if tool is None:
            return f"ERROR: unknown tool {name}"
        try:
            parsed = tool.params.model_validate_json(args_json or "{}")
            result = await tool.execute(parsed, tool_ctx)
            return result.output
        except Exception as e:  # noqa: BLE001 — tool errors feed back to the model
            return f"ERROR: {type(e).__name__}: {e}"

    async def _tool_loop(
        self, ctx: NodeContext, *, seed_messages: list[dict], tools: Any,
        cwd: "Path", max_iterations: int, leak_text: bool = False,
        hooks: "ToolLoopHooks" = _DEFAULT_HOOKS,
    ) -> list[dict]:
        """Unified bounded read/act loop for the loop nodes (implementer/explorer/verifier).
        Streams rounds (text-leak per `leak_text`), runs each round's tool calls in `cwd`,
        clamps each output via hooks.clamp for the model copy (the sink always gets the full
        output), records side effects via hooks.record, and calls hooks.after_round after
        each tool round (where a node re-clamps prior rounds / appends a nudge / checks the
        tree). Returns the transcript minus the seed system prompt (mirrors _read_loop)."""
        messages = list(seed_messages)
        tool_ctx = ToolContext(turn_id=self.name, cancel=ctx.cancel, cwd=cwd, ask=allow_all)
        schemas = tools.schemas()
        await hooks.before_loop()
        for i in range(max_iterations):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            text, calls = await self._stream_llm_round(ctx, messages, schemas, leak_text=leak_text)
            assistant: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                assistant["tool_calls"] = [
                    {"id": cid, "type": "function",
                     "function": {"name": name, "arguments": args or "{}"}}
                    for cid, name, args in calls]
            messages.append(assistant)
            if not calls:
                break
            rnd = _LoopRound(index=i, calls=calls, tool_msgs={}, full_output={},
                             messages=messages)
            for cid, name, args in calls:
                if ctx.sink is not None:
                    ctx.sink.tool_started(cid, name, _safe_args(args))
                output = await self._run_tool(tools, name, args, tool_ctx)
                hooks.record(name, args, output)
                if ctx.sink is not None:
                    if output.startswith("ERROR:"):
                        ctx.sink.tool_failed(cid, output)
                    else:
                        ctx.sink.tool_finished(cid, output)
                msg: dict[str, Any] = {"role": "tool", "tool_call_id": cid,
                                       "content": hooks.clamp(output)}
                messages.append(msg)
                rnd.tool_msgs[cid] = msg
                rnd.full_output[cid] = output
            await hooks.after_round(rnd)
        return messages[1:]

    async def _read_loop(
        self, ctx: NodeContext, tools: Any, seed_messages: list[dict],
        *, max_iterations: int = READ_LOOP_MAX_ITERATIONS,
        cwd: "Path | None" = None,
    ) -> list[dict]:
        """Bounded read/act loop. Streams rounds that may call `tools`, runs them, and
        feeds results back. Returns the transcript to hand to _dispatch as extra_messages
        (seed system dropped, mirrors ExploringNode handing messages[1:] to its emit
        stage). Stops when the model makes no tool call or the cap hits. `cwd` defaults
        to the process cwd (the interviewer's behavior); loop nodes pass their own
        work-tree."""
        messages = list(seed_messages)
        tool_ctx = ToolContext(turn_id=self.name, cancel=ctx.cancel,
                               cwd=cwd if cwd is not None else Path.cwd(), ask=allow_all)
        schemas = tools.schemas()
        for _ in range(max_iterations):
            if ctx.cancel.is_set():
                raise asyncio.CancelledError(f"{self.name} cancelled")
            text, calls = await self._stream_tools(ctx, messages, schemas)
            assistant: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                assistant["tool_calls"] = [
                    {"id": cid, "type": "function",
                     "function": {"name": name, "arguments": args or "{}"}}
                    for cid, name, args in calls]
            messages.append(assistant)
            if not calls:
                break
            for cid, name, args in calls:
                if ctx.sink is not None:
                    ctx.sink.tool_started(cid, name, _safe_args(args))
                output = await self._run_tool(tools, name, args, tool_ctx)
                if ctx.sink is not None:
                    if output.startswith("ERROR:"):
                        ctx.sink.tool_failed(cid, output)
                    else:
                        ctx.sink.tool_finished(cid, output)
                messages.append({"role": "tool", "tool_call_id": cid,
                                 "content": clamp_tool_output(output)})
        return messages[1:]   # drop the read-loop system prompt; keep user+rounds
