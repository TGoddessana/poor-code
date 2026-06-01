import asyncio
import json
import uuid
import pytest
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness import build_default_registry, Driver, route
from poor_code.domain.session.models import SessionState, Cursor, Phase, Request, RequestKind
from poor_code.domain.session.store import SessionStore
from poor_code.domain.project_map.models import ProjectMap, FileEntry, Symbol, SymbolKind
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class FakeLLMClient:
    """Routes canned structured output by which tool the node offered, so the
    same client drives both the Router (classify_request) and the Locator
    (emit_code_context) along their real agent paths."""
    def __init__(self, *, code_context, kind="engineering"):
        self._by_tool = {
            "classify_request": {"kind": kind, "reason": "test"},
            "emit_code_context": code_context,
        }

    async def stream(self, messages, tools):
        name = tools[0]["function"]["name"]
        args = json.dumps(self._by_tool[name])
        yield ToolCallStarted(call_id="c1", name=name)
        yield ToolCallInputDelta(call_id="c1", json_delta=args)
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _map():
    sym = Symbol(name="login", kind=SymbolKind.FUNCTION, lineno=10,
                 signature=None, doc=None, calls=(), called_by=())
    fe = FileEntry(path="src/auth.py", language="python", content_hash="h",
                   symbols=(sym,), imports=(), imported_by=(), tests=())
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(fe,), parse_errors=())


@pytest.mark.asyncio
async def test_engineering_request_flows_to_code_context_and_checkpoints(tmp_path: Path):
    llm = FakeLLMClient(code_context={"candidates": [{"file": "src/auth.py", "symbol": "login"}],
                                      "confusers": [], "related_tests": []})
    registry = build_default_registry(llm=llm, project_map=_map())

    store = SessionStore(tmp_path)
    sid = uuid.uuid4().hex
    driver = Driver(registry, route, on_step=lambda s: store.write_session_state(sid, s))

    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="fix the login bug", kind=RequestKind.ENGINEERING),
    )
    final = await driver.run(start, asyncio.Event())

    # graph parked at interviewer (not implemented), with understanding produced
    assert final.cursor.current_node == "interviewer"
    assert final.understanding.candidates[0].symbol == "login"

    # persisted: reloading the checkpoint yields the same understanding
    reloaded = store.read_session_state(sid)
    assert reloaded.understanding.candidates[0].file == "src/auth.py"
    assert reloaded.cursor.current_node == "interviewer"


@pytest.mark.asyncio
async def test_empty_candidates_bounce_back_to_locator_then_escalate(tmp_path: Path):
    # Locator finds nothing → UnderstandingGate fires the first real back-edge.
    llm = FakeLLMClient(code_context={"candidates": [], "confusers": [], "related_tests": []})
    registry = build_default_registry(llm=llm, project_map=_map())

    visited: list[str] = []
    driver = Driver(registry, route, on_step=lambda s: visited.append(s.cursor.current_node))
    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="add a thing", kind=RequestKind.ENGINEERING),
    )
    final = await driver.run(start, asyncio.Event())

    # The cursor looped back to the locator (the back-edge actually fired) ...
    assert visited.count("locator") == 2
    # ... and, still empty on the retry, the gate escalated to the user.
    assert final.cursor.current_node == "user"


@pytest.mark.asyncio
async def test_lightweight_request_parks_at_fast_path(tmp_path: Path):
    registry = build_default_registry(
        llm=FakeLLMClient(kind="lightweight",
                          code_context={"candidates": [], "confusers": [], "related_tests": []}),
        project_map=_map())
    driver = Driver(registry, route)
    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="반갑다 너는 누구냐", kind=RequestKind.ENGINEERING),  # Router reclassifies
    )
    final = await driver.run(start, asyncio.Event())
    assert final.cursor.current_node == "fast_path"   # handed off to legacy agent.py path
    assert final.understanding is None                 # never reached locator
