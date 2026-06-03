"""The explorer probes the environment once and carries it on CodeContext; the
planner and implementer surface it so they pick a stack that exists (a bench task
on ubuntu-24-04 has python3 but no node — the implementer must not pick Node)."""
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes import explorer as explorer_mod
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import (
    CodeContext, EditScope, Plan, Request, RequestKind, Requirement, SessionState,
    Task,
)
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)

_SENTINEL = "ENV_SENTINEL: python3 yes / node NO"


def _map():
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(), parse_errors=())


class _ExplorerLLM:
    """Stage ① stops immediately; stage ② emits a code context."""
    def __init__(self):
        self.seen = []

    async def stream(self, messages, tools, response_format=None):
        self.seen.append(messages)
        name = tools[0]["function"]["name"] if tools else ""
        if name == "emit_code_context":
            payload = json.dumps({"candidates": [], "confusers": [], "related_tests": [],
                                  "search_notes": "", "grounding": "greenfield", "summary": "s"})
            yield ToolCallStarted(call_id="c1", name=name)
            yield ToolCallInputDelta(call_id="c1", json_delta=payload)
            yield ToolCallEnded(call_id="c1")
            yield FinishedReason(reason="tool_calls")
        else:
            yield TextDelta(text="done")
            yield FinishedReason(reason="stop")


@pytest.mark.asyncio
async def test_explorer_probes_and_carries_environment(monkeypatch, tmp_path):
    async def fake_probe(cwd, timeout=20.0):
        return _SENTINEL
    monkeypatch.setattr(explorer_mod, "probe_environment", fake_probe)

    llm = _ExplorerLLM()
    node = ExploringNode(llm, project_map=_map(),
                         tools=ToolRegistry([]))
    res = await node.run(NodeContext(SessionState(
        request=Request(raw_text="build a server", kind=RequestKind.ENGINEERING)),
        cancel=asyncio.Event()))

    assert res.output.environment == _SENTINEL
    # the recon model also sees the environment while exploring
    assert any(_SENTINEL in m["content"] for msgs in llm.seen for m in msgs
               if m.get("role") == "user")


def _state_with_env():
    return SessionState(
        request=Request(raw_text="build a fib server", kind=RequestKind.ENGINEERING),
        requirement=Requirement(summary="fib server on :3000"),
        understanding=CodeContext(environment=_SENTINEL, summary="greenfield"),
    )


def test_planner_prompt_surfaces_environment():
    msgs = Planner(llm=None, project_map=_map()).build_messages(_state_with_env())
    assert any(_SENTINEL in m["content"] for m in msgs)


def test_implementer_prompt_surfaces_environment(tmp_path):
    task = Task(id="t1", title="impl", purpose="p", description="d",
                edit_scope=EditScope(editable=("server.py",)),
                how_to_validate="python3 -c 'pass'")
    state = SessionState(
        request=Request(raw_text="build a fib server", kind=RequestKind.ENGINEERING),
        requirement=Requirement(summary="fib server"),
        understanding=CodeContext(environment=_SENTINEL),
        plan=Plan(tasks=(task,), deps=()),
    )
    prompt = Implementer(llm=None, cwd=tmp_path, tools=None)._prompt(state, task)
    assert _SENTINEL in prompt
