"""Agent — the inner loop. Calls the LLM, executes tools, feeds results
back, until the model produces a final assistant message (no tool_calls)
or MAX_ITERATIONS is reached.

There is no Agent Protocol: tests substitute at the LLMClient boundary
via FakeLLMClient, not at the Agent boundary.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from poor_code.domain.tool.base import ToolContext, allow_all
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    Command,
    Event,
    RunSlashCommand,
    SendPrompt,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    TurnEnded,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
)
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted as ProviderToolCallStarted,
    UsageEnded,
)
from poor_code.provider.registry import ModelPricing, lookup


MAX_ITERATIONS = 8


def _compute_cost(
    pricing: ModelPricing | None,
    input_tokens: int,
    output_tokens: int,
) -> float:
    if pricing is None:
        return 0.0
    return (
        input_tokens * pricing.input_per_1m
        + output_tokens * pricing.output_per_1m
    ) / 1_000_000


@runtime_checkable
class _LLMClientLike(Protocol):
    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]: ...


@dataclass
class _PendingCall:
    call_id: str
    name: str
    args_json: str = ""


class Agent:
    def __init__(
        self,
        llm: _LLMClientLike,
        tools: ToolRegistry,
        assembler: TurnAssembler,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.assembler = assembler
        self.history: list[dict[str, Any]] = []

    async def run(self, cmd: Command, cancel: asyncio.Event) -> AsyncIterator[Event]:
        turn_id = uuid.uuid4().hex
        start_time = time.monotonic()
        model_name = getattr(self.llm, "model", "") or ""
        pricing = lookup(model_name).pricing
        cmd_id = getattr(cmd, "cmd_id", "")

        user_text = self._cmd_to_text(cmd)
        if user_text is None:
            yield TurnFailed(turn_id=turn_id, error=f"unsupported command: {type(cmd).__name__}")
            return

        self.history.append({"role": "user", "content": user_text})
        yield TurnStarted(cmd_id=cmd_id, turn_id=turn_id)

        ctx = ToolContext(
            turn_id=turn_id, cancel=cancel, cwd=Path.cwd(), ask=allow_all
        )

        for _iteration in range(MAX_ITERATIONS):
            if cancel.is_set():
                yield TurnFailed(turn_id=turn_id, error="cancelled")
                return

            assistant_text = ""
            pending: dict[str, _PendingCall] = {}
            call_order: list[str] = []

            try:
                api_messages = await self.assembler.build(self.history, ctx.cwd)
                async for ev in self.llm.stream(
                    messages=api_messages, tools=self.tools.schemas()
                ):
                    if cancel.is_set():
                        yield TurnFailed(turn_id=turn_id, error="cancelled")
                        return
                    match ev:
                        case TextDelta(text=t):
                            assistant_text += t
                            yield AssistantTextDelta(turn_id=turn_id, text=t)
                        case ProviderToolCallStarted(call_id=cid, name=name):
                            pending[cid] = _PendingCall(call_id=cid, name=name)
                            call_order.append(cid)
                        case ToolCallInputDelta(call_id=cid, json_delta=delta):
                            if cid in pending:
                                pending[cid].args_json += delta
                        case ToolCallEnded():
                            pass  # finalization handled at FinishedReason
                        case UsageEnded(input_tokens=in_tok, output_tokens=out_tok):
                            yield UsageUpdated(
                                turn_id=turn_id,
                                input_tokens=in_tok,
                                output_tokens=out_tok,
                                cost_usd=_compute_cost(pricing, in_tok, out_tok),
                            )
                        case FinishedReason():
                            break
            except Exception as e:
                yield TurnFailed(turn_id=turn_id, error=f"{type(e).__name__}: {e}")
                return

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": assistant_text}
            if call_order:
                assistant_msg["tool_calls"] = [
                    {
                        "id": cid,
                        "type": "function",
                        "function": {
                            "name": pending[cid].name,
                            "arguments": pending[cid].args_json or "{}",
                        },
                    }
                    for cid in call_order
                ]
            self.history.append(assistant_msg)

            if not call_order:
                yield AssistantMessageCompleted(turn_id=turn_id, text=assistant_text)
                yield TurnEnded(
                    turn_id=turn_id,
                    duration_sec=time.monotonic() - start_time,
                    model=model_name,
                )
                return

            # Execute tool calls in order, feed results back, loop again.
            turn_ended = False
            for cid in call_order:
                async for ev in self._execute_tool_call(turn_id, pending[cid], ctx):
                    yield ev
                    if isinstance(ev, TurnFailed):
                        turn_ended = True
                if turn_ended:
                    return

        # Max iterations exhausted.
        yield TurnEnded(
            turn_id=turn_id,
            duration_sec=time.monotonic() - start_time,
            model=model_name,
        )

    async def _execute_tool_call(
        self, turn_id: str, call: _PendingCall, ctx: ToolContext
    ) -> AsyncIterator[Event]:
        tool = self.tools.get(call.name)
        if tool is None:
            err = f"unknown tool: {call.name}"
            yield ToolCallStarted(
                turn_id=turn_id, tool_call_id=call.call_id,
                tool_name=call.name, args={},
            )
            yield ToolCallFailed(
                turn_id=turn_id, tool_call_id=call.call_id, error=err,
            )
            self.history.append({
                "role": "tool", "tool_call_id": call.call_id,
                "content": f"ERROR: {err}",
            })
            return

        try:
            args = tool.params.model_validate_json(call.args_json or "{}")
        except Exception as e:
            err = f"invalid arguments: {e}"
            yield ToolCallStarted(
                turn_id=turn_id, tool_call_id=call.call_id,
                tool_name=call.name, args={},
            )
            yield ToolCallFailed(
                turn_id=turn_id, tool_call_id=call.call_id, error=err,
            )
            self.history.append({
                "role": "tool", "tool_call_id": call.call_id,
                "content": f"ERROR: {err}",
            })
            return

        yield ToolCallStarted(
            turn_id=turn_id, tool_call_id=call.call_id,
            tool_name=call.name, args=args.model_dump(),
        )

        task = asyncio.create_task(tool.execute(args, ctx))
        while not task.done():
            if ctx.cancel.is_set():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                yield ToolCallFailed(
                    turn_id=turn_id, tool_call_id=call.call_id, error="cancelled",
                )
                yield TurnFailed(turn_id=turn_id, error="cancelled")
                return
            await asyncio.sleep(0.05)

        try:
            result = task.result()
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            yield ToolCallFailed(
                turn_id=turn_id, tool_call_id=call.call_id, error=err,
            )
            self.history.append({
                "role": "tool", "tool_call_id": call.call_id,
                "content": f"ERROR: {err}",
            })
            return

        yield ToolCallFinished(
            turn_id=turn_id, tool_call_id=call.call_id, result=result.output,
        )
        self.history.append({
            "role": "tool", "tool_call_id": call.call_id,
            "content": result.output,
        })

    @staticmethod
    def _cmd_to_text(cmd: Command) -> str | None:
        match cmd:
            case SendPrompt(text=t):
                return t
            case RunSlashCommand(name=n, args=a):
                return f"/{n} {' '.join(a)}".strip()
            case _:
                return None
