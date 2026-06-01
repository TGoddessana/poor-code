"""Show the harness graph's FIRST back-edge actually firing — no real LLM needed.

The Locator is fed a fake LLM that always returns an EMPTY CodeContext (found
nothing). The UnderstandingGate then fires repair(understanding), which route()
turns into a back-edge to the locator. Still empty on the retry → escalate(user).

Run:
    .venv/bin/python scripts/harness_loop_demo.py
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness import Driver, build_default_registry, route
from poor_code.domain.project_map.models import (
    FileEntry, ProjectMap, Symbol, SymbolKind,
)
from poor_code.domain.session.models import (
    Cursor, Phase, Request, RequestKind, SessionState,
)
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)


class _EmptyLocatorLLM:
    """A fake LLM: makes the Locator emit whatever CodeContext we hand it."""

    def __init__(self, args_obj) -> None:
        self._args = json.dumps(args_obj)

    async def stream(self, messages, tools):
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=self._args)
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _tiny_map() -> ProjectMap:
    sym = Symbol(name="login", kind=SymbolKind.FUNCTION, lineno=10,
                 signature=None, doc=None, calls=(), called_by=())
    fe = FileEntry(path="src/auth.py", language="python", content_hash="h",
                   symbols=(sym,), imports=(), imported_by=(), tests=())
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(fe,), parse_errors=())


def main() -> None:
    # Force the Locator to find nothing → the gate has something to complain about.
    llm = _EmptyLocatorLLM({"candidates": [], "confusers": [], "related_tests": []})
    registry = build_default_registry(llm=llm, project_map=_tiny_map())

    driver = Driver(registry, route)
    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="add a thing that matches nothing",
                        kind=RequestKind.ENGINEERING),
    )
    final = asyncio.run(driver.run(start, asyncio.Event()))

    print("REQUEST: 'add a thing that matches nothing' (Locator forced to find 0 candidates)\n")
    print("WALK (start @ router):")
    print(f"  0. {'(start)':18s}                       router")
    for i, t in enumerate(final.history, 1):
        is_back = t.to_node == "locator" and t.trigger.name == "GATE"
        tag = "   <<<<<< BACK-EDGE FIRED" if is_back else ""
        print(f"  {i}. {t.from_node:18s} --[{t.trigger.name:8s}]-->  {t.to_node}{tag}")

    visited = 1 + sum(1 for t in final.history if t.to_node == "locator")
    print(f"\nFINAL cursor = {final.cursor.current_node!r}  (transitions: {len(final.history)})")
    print(f"locator visited {visited}x → the graph looped, then escalated.")


if __name__ == "__main__":
    main()
