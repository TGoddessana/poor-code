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
async def test_planner_system_prompt_teaches_patch_size_and_skeleton():
    llm = FakeLLM({"tasks": []})
    state = SessionState(requirement=Requirement(summary="x"))
    await Planner(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    system = llm.seen_messages[0]["content"]
    # Core rubric: patch-sized deliverables
    assert "patch" in system.lower()
    # Markdown-first design
    assert "plan_md" in system
    assert "markdown" in system.lower()
    # Skeleton fields
    assert "editable" in system.lower()
    assert "depends_on" in system.lower()
    # Implementer delegation (planner does NOT write steps)
    assert "implementer" in system.lower()
