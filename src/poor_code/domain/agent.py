"""Agent Protocol.

The body of this module — real Agent class, inner loop, hooks wiring — is
deferred per spec until the first real Provider lands. Here we define ONLY
the Protocol that the UI side depends on, so PoorCodeApp can be typed and
test doubles (EchoAgent, FakeAgent) can be substituted freely.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Protocol, runtime_checkable

from poor_code.messages import Command, Event


@runtime_checkable
class Agent(Protocol):
    async def run(
        self, cmd: Command, cancel: asyncio.Event
    ) -> AsyncIterator[Event]:
        """Process a Command, yield Events until the turn ends or is cancelled.

        Implementations MUST be cooperative w.r.t. `cancel.is_set()` and yield
        a terminal Event (TurnEnded or TurnFailed) before returning.
        """
        ...
