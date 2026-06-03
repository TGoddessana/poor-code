import asyncio, json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import Requirement, SessionState
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.seen_messages = None
    async def stream(self, messages, tools, response_format=None):
        self.seen_messages = messages
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=json.dumps(self.payload))
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _map():
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(), parse_errors=())


@pytest.mark.asyncio
async def test_planner_system_prompt_teaches_patch_size_and_example():
    llm = FakeLLM({"tasks": [], "deps": []})
    state = SessionState(requirement=Requirement(summary="x"))
    await Planner(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    system = llm.seen_messages[0]["content"]
    # rubric signals
    assert "patch" in system.lower()
    assert "one primary" in system.lower() or "one editable" in system.lower()
    assert "observable" in system.lower()
    # worked example with a runnable validation
    assert "curl" in system
    assert "process.exit(1)" in system
    # server-cleanup teaching (issue: orphaned background server)
    assert "kill" in system
    # t3 is behavioral (npm start), not a string check
    assert "npm start" in system
