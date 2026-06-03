import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.planner import Planner
from poor_code.domain.project_map.models import FileEntry, ProjectMap, Symbol, SymbolKind
from poor_code.domain.session.models import (
    CodeContext,
    CodeRef,
    GroundingStatus,
    Requirement,
    SessionState,
)
from poor_code.provider.events import (
    FinishedReason,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.seen_messages = None
        self.seen_tools = None

    async def stream(self, messages, tools):
        self.seen_messages = messages
        self.seen_tools = tools
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=json.dumps(self.payload))
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _map():
    sym = Symbol(
        name="login",
        kind=SymbolKind.FUNCTION,
        lineno=10,
        signature="def login(provider: str) -> None",
        doc=None,
        calls=(),
        called_by=(),
    )
    fe = FileEntry(
        path="src/auth.py",
        language="python",
        content_hash="h",
        symbols=(sym,),
        imports=(),
        imported_by=(),
        tests=("tests/test_auth.py",),
    )
    return ProjectMap(
        version=2,
        generated_at=datetime.now(UTC),
        cwd=Path("."),
        files=(fe,),
        parse_errors=(),
    )


def _state():
    return SessionState(
        requirement=Requirement(
            summary="add google login",
            acceptance=("google provider file exists", "login can select google"),
            out_of_scope=("oauth callback UI",),
            assumptions=("reuse provider registry",),
        ),
        understanding=CodeContext(
            candidates=(CodeRef(file="src/auth.py", symbol="login"),),
            related_tests=(CodeRef(file="tests/test_auth.py"),),
        ),
    )


@pytest.mark.asyncio
async def test_planner_emits_plan_with_deterministic_task_ids():
    llm = FakeLLM({
        "tasks": [
            {
                "title": "Add Google provider",
                "purpose": "Support google login provider",
                "description": "Create the provider module.",
                "edit_scope": {
                    "editable": ["src/provider/google.py"],
                    "readonly": ["src/auth.py"],
                    "forbidden": ["src/poor_code/messages.py"],
                },
                "how_to_validate": "pytest tests/test_auth.py",
            },
            {
                "title": "Wire provider selection",
                "purpose": "Expose google through login",
                "edit_scope": {"editable": ["src/auth.py"]},
                "how_to_validate": "pytest tests/test_auth.py",
            },
        ],
        "deps": [{"task_id": "t2", "depends_on": "t1"}],
    })
    res = await Planner(llm, project_map=_map()).run(
        NodeContext(_state(), cancel=asyncio.Event())
    )

    plan = res.output
    assert plan.tasks[0].id == "t1"
    assert plan.tasks[1].id == "t2"
    assert plan.tasks[0].edit_scope.editable == ("src/provider/google.py",)
    assert plan.tasks[0].how_to_validate == "pytest tests/test_auth.py"
    assert plan.deps[0].depends_on == "t1"


@pytest.mark.asyncio
async def test_planner_prompt_includes_requirement_and_code_context():
    llm = FakeLLM({"tasks": [], "deps": []})
    await Planner(llm, project_map=_map()).run(
        NodeContext(_state(), cancel=asyncio.Event())
    )
    prompt = llm.seen_messages[-1]["content"]
    assert "REQUIREMENT:" in prompt
    assert "add google login" in prompt
    assert "src/auth.py::login" in prompt
    assert "def login(provider: str) -> None" in prompt


@pytest.mark.asyncio
async def test_planner_prompt_flags_greenfield_mode():
    state = SessionState(
        requirement=Requirement(summary="create hello.txt"),
        understanding=CodeContext(candidates=(), grounding=GroundingStatus.GREENFIELD),
    )
    llm = FakeLLM({"tasks": [], "deps": []})
    await Planner(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    assert "MODE: greenfield" in llm.seen_messages[-1]["content"]


@pytest.mark.asyncio
async def test_planner_prompt_no_greenfield_flag_when_grounded():
    # _state() uses real candidates with default grounding=not_found
    llm = FakeLLM({"tasks": [], "deps": []})
    await Planner(llm, project_map=_map()).run(NodeContext(_state(), cancel=asyncio.Event()))
    assert "MODE: greenfield" not in llm.seen_messages[-1]["content"]
