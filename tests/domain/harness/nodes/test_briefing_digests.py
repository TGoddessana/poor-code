import asyncio, json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.interviewer import Interviewer
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import (
    CodeContext, FileExcerpt, GroundingStatus, Request, RequestKind, Requirement,
    SessionState)
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


def _understanding():
    return CodeContext(
        candidates=(), grounding=GroundingStatus.GREENFIELD,
        summary="needs an 800x600 P6 PPM; validate by L2 similarity >= 0.8",
        excerpts=(FileExcerpt(path="orig.sh", text="ffmpeg scale=800:600"),),
    )


@pytest.mark.asyncio
async def test_interviewer_digest_includes_summary_and_excerpt():
    state = SessionState(
        request=Request(raw_text="reconstruct image", kind=RequestKind.ENGINEERING),
        understanding=_understanding(),
    )
    llm = FakeLLM({"action": "done",
                   "requirement": {"summary": "s", "acceptance": [], "out_of_scope": [],
                                   "assumptions": [], "open_questions": []}})
    await Interviewer(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "summary: needs an 800x600" in prompt
    assert "orig.sh" in prompt
    assert "ffmpeg scale=800:600" in prompt


@pytest.mark.asyncio
async def test_interviewer_digest_marks_digest_clipped_excerpt_truncated():
    big = CodeContext(
        grounding=GroundingStatus.GREENFIELD,
        excerpts=(FileExcerpt(path="big.txt", text="A" * 700, truncated=False),),
    )
    state = SessionState(
        request=Request(raw_text="x", kind=RequestKind.ENGINEERING),
        understanding=big,
    )
    llm = FakeLLM({"action": "done",
                   "requirement": {"summary": "s", "acceptance": [], "out_of_scope": [],
                                   "assumptions": [], "open_questions": []}})
    await Interviewer(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "--- big.txt (truncated) ---" in prompt
    assert " …" in prompt


@pytest.mark.asyncio
async def test_planner_digest_includes_summary_and_excerpt():
    state = SessionState(
        requirement=Requirement(summary="reconstruct image"),
        understanding=_understanding(),
    )
    llm = FakeLLM({"tasks": [], "deps": []})
    await Planner(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "summary: needs an 800x600" in prompt
    assert "orig.sh" in prompt
