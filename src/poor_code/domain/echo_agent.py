"""EchoAgent — minimal demo Agent for v0 wiring and tests.

Yields a deterministic Event sequence that echoes the user's input. Has no
LLM dependency. Used by `cli.py` as the default Agent for `uv run poor-code`
and by integration tests to drive the UI flow.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    Command,
    Event,
    RunSlashCommand,
    SendPrompt,
    TurnEnded,
    TurnFailed,
    TurnStarted,
)


class EchoAgent:
    """Implements the Agent Protocol. No state retained between turns."""

    async def run(
        self, cmd: Command, cancel: asyncio.Event
    ) -> AsyncIterator[Event]:
        turn_id = uuid.uuid4().hex

        # Always emit TurnStarted first (gives UI a turn_id to bind to).
        if isinstance(cmd, SendPrompt):
            user_text = cmd.text
            cmd_id = cmd.cmd_id
        elif isinstance(cmd, RunSlashCommand):
            user_text = f"/{cmd.name} {' '.join(cmd.args)}".strip()
            cmd_id = cmd.cmd_id
        else:
            yield TurnFailed(turn_id=turn_id, error=f"unsupported command: {type(cmd).__name__}")
            return

        yield TurnStarted(cmd_id=cmd_id, turn_id=turn_id)

        if cancel.is_set():
            yield TurnFailed(turn_id=turn_id, error="cancelled")
            return

        reply = f"echo: {user_text}"
        # Stream the reply word-by-word so the UI shows incremental updates.
        words = reply.split(" ")
        emitted = ""
        for i, word in enumerate(words):
            if cancel.is_set():
                yield TurnFailed(turn_id=turn_id, error="cancelled")
                return
            chunk = (" " if i > 0 else "") + word
            emitted += chunk
            yield AssistantTextDelta(turn_id=turn_id, text=chunk)
            await asyncio.sleep(0.01)  # cooperative yield + tiny visual stagger

        yield AssistantMessageCompleted(turn_id=turn_id, text=emitted)
        yield TurnEnded(turn_id=turn_id)
