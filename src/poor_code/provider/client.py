"""LLMClient — assembles a Route + httpx.AsyncClient into a streaming API.

stream() is an async generator of provider-neutral LLMEvents. One instance
is reused across turns; each call to stream() opens a fresh HTTP request
and a fresh parser instance (so per-stream state in the Protocol is isolated).
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from poor_code.provider.events import LLMEvent
from poor_code.provider.route import Route

# Timeout defaults. The read timeout is an IDLE timeout: the maximum gap between
# streamed byte chunks, NOT a cap on total response time. A long-but-progressing
# completion keeps resetting it; a provider that stalls (stops sending) trips it.
# read=None (the old value) turned any such stall into an infinite hang — the
# single worst harness failure mode in benchmarking, where one wedged call ate
# the entire run budget.
DEFAULT_CONNECT_TIMEOUT = 15.0
DEFAULT_IDLE_TIMEOUT = 120.0
DEFAULT_WRITE_TIMEOUT = 30.0
# Retries apply ONLY to transport failures that happen before the first event is
# yielded (a stalled connect / first token). Once we have emitted events the
# stream is half-consumed downstream and cannot be safely restarted.
DEFAULT_MAX_RETRIES = 2


class LLMClient:
    def __init__(
        self,
        route: Route,
        base_url: str,
        model: str,
        provider_name: str = "",
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        write_timeout: float = DEFAULT_WRITE_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.route = route
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_name = provider_name
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=idle_timeout,
            write=write_timeout,
            pool=connect_timeout,
        )
        self._max_retries = max_retries

    @property
    def capabilities(self):
        return self.route.capabilities

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[LLMEvent]:
        body = self.route.protocol.build_body(
            messages=messages, tools=tools, model=self.model,
            capabilities=self.route.capabilities,
            response_format=response_format,
        )
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        self.route.auth.apply(headers)
        url = self.base_url + self.route.endpoint

        attempt = 0
        while True:
            # A fresh parser per attempt so a retried request starts from a clean
            # per-stream state.
            parser = self.route.protocol.for_stream()
            yielded = False
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as http:
                    async with http.stream(
                        "POST", url, headers=headers, json=body
                    ) as resp:
                        if resp.is_error:
                            await resp.aread()
                            detail = (resp.text or "").strip()
                            msg = f"HTTP {resp.status_code} from {url}"
                            if detail:
                                msg += f": {detail[:500]}"
                            # Not a transport stall — a definite answer. Never retried
                            # (HTTPStatusError is not an httpx.TransportError).
                            raise httpx.HTTPStatusError(
                                msg, request=resp.request, response=resp)
                        async for payload in self.route.framing.frames(
                            resp.aiter_bytes()
                        ):
                            try:
                                chunk = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            for event in parser.parse_chunk(chunk):
                                yielded = True
                                yield event
                return
            except httpx.TransportError:
                # Stall / connection failure. Retry only if nothing was emitted yet
                # and we have budget left; otherwise propagate.
                if yielded or attempt >= self._max_retries:
                    raise
                attempt += 1
                continue
