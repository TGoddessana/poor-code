import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, CodeContext, GroundingStatus, Requirement,
    SessionState,
)
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)


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
async def test_planner_prompt_includes_global_acceptance():
    state = SessionState(
        requirement=Requirement(summary="create hello.txt"),
        understanding=CodeContext(grounding=GroundingStatus.GREENFIELD),
        acceptance=AcceptanceSpec(checks=(
            AcceptanceCheck(criterion="content",
                            command="printf '%s' \"$E\" | diff - hello.txt"),)),
    )
    llm = FakeLLM({"tasks": [], "deps": []})
    await Planner(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "GLOBAL ACCEPTANCE" in prompt
    assert "diff - hello.txt" in prompt
