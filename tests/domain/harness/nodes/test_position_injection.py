import asyncio, json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.harness.nodes.interviewer import Interviewer
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import (
    Cursor, EditScope, Phase, Plan, Request, RequestKind, Requirement,
    SessionState, Task, TaskStatus)
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.write import WriteTool
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class FakeStructLLM:
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
async def test_planner_prompt_has_position_block():
    llm = FakeStructLLM({"tasks": [], "deps": []})
    state = SessionState(requirement=Requirement(summary="x"))
    await Planner(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    assert "HARNESS POSITION" in llm.seen_messages[-1]["content"]


@pytest.mark.asyncio
async def test_interviewer_prompt_has_position_block():
    llm = FakeStructLLM({"action": "done",
                         "requirement": {"summary": "s", "acceptance": [], "out_of_scope": [],
                                         "assumptions": [], "open_questions": []}})
    state = SessionState(request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    await Interviewer(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    assert "HARNESS POSITION" in llm.seen_messages[-1]["content"]


def test_implementer_prompt_has_position_block():
    node = Implementer(llm=None, cwd=Path("."), tools=ToolRegistry([WriteTool()]))
    task = Task(id="t1", title="x", purpose="p",
                edit_scope=EditScope(editable=("a",)), how_to_validate="true",
                status=TaskStatus.ACTIVE)
    state = SessionState(
        plan=Plan(tasks=(task,)),
        cursor=Cursor(phase=Phase.IMPLEMENTING, current_node="implementer", task_id="t1"))
    assert "HARNESS POSITION" in node._prompt(state, task)


class ScriptedLLM:
    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls = []
    async def stream(self, messages, tools, response_format=None):
        self.calls.append({"messages": list(messages)})
        for ev in self._rounds.pop(0):
            yield ev


@pytest.mark.asyncio
async def test_explorer_seed_prompt_has_position_block():
    llm = ScriptedLLM([
        [TextDelta(text="done"), FinishedReason(reason="stop")],
        [ToolCallStarted(call_id="o1", name="emit_code_context"),
         ToolCallInputDelta(call_id="o1", json_delta=json.dumps(
             {"candidates": [], "confusers": [], "related_tests": [],
              "grounding": "greenfield", "summary": ""})),
         ToolCallEnded(call_id="o1"), FinishedReason(reason="tool_calls")],
    ])
    state = SessionState(request=Request(raw_text="x", kind=RequestKind.ENGINEERING))
    node = ExploringNode(llm, project_map=_map(), tools=ToolRegistry([ReadTool()]))
    await node.run(NodeContext(state=state, cancel=asyncio.Event()))
    seed_user = llm.calls[0]["messages"][1]["content"]
    assert "HARNESS POSITION" in seed_user
