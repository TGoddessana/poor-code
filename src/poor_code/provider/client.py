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


class LLMClient:
    def __init__(
        self,
        route: Route,
        base_url: str,
        model: str,
        provider_name: str = "",
    ) -> None:
        self.route = route
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_name = provider_name

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
        parser = self.route.protocol.for_stream()  # fresh per-stream parser
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        self.route.auth.apply(headers)
        url = self.base_url + self.route.endpoint

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None)) as http:
            async with http.stream("POST", url, headers=headers, json=body) as resp:
                if resp.is_error:
                    await resp.aread()
                    detail = (resp.text or "").strip()
                    msg = f"HTTP {resp.status_code} from {url}"
                    if detail:
                        msg += f": {detail[:500]}"
                    raise httpx.HTTPStatusError(msg, request=resp.request, response=resp)
                async for payload in self.route.framing.frames(resp.aiter_bytes()):
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    for event in parser.parse_chunk(chunk):
                        yield event
