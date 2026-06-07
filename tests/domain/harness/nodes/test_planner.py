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
    Request,
    RequestKind,
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

    async def stream(self, messages, tools, response_format=None):
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
async def test_planner_surfaces_repair_hint_and_prior_plan():
    from dataclasses import replace

    from poor_code.domain.session.models import EditScope, Plan, Task
    prior = Plan(tasks=(Task(id="t1", title="add f", purpose="p",
                             edit_scope=EditScope(editable=())),))
    state = replace(_state().with_repair_hint("Task t1 has no editable paths."), plan=prior)
    llm = FakeLLM({"file_plan": [], "tasks": []})
    await Planner(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    user_msg = llm.seen_messages[-1]["content"]
    assert "Task t1 has no editable paths." in user_msg
    assert "PRIOR PLAN" in user_msg and "add f" in user_msg


def test_system_prompt_carries_strengthening_levers():
    from poor_code.domain.harness.nodes.planner import _SYSTEM
    low = _SYSTEM.lower()
    assert "do not invent" in low
    assert "editable" in low  # tasks carry editable files
    assert "implementer" in low  # delegates steps to implementer


@pytest.mark.asyncio
async def test_planner_parses_skeleton_task_with_editable_and_deps():
    payload = {
        "tasks": [
            {"id": "t1", "title": "add f", "editable": ["x.py", "tests/x_test.py"], "depends_on": []},
            {"id": "t2", "title": "wire f", "editable": ["main.py"], "depends_on": ["t1"]},
        ],
    }
    res = await Planner(FakeLLM(payload), project_map=_map()).run(
        NodeContext(_state(), cancel=asyncio.Event())
    )
    plan = res.output
    assert plan.tasks[0].id == "t1"
    assert plan.tasks[0].edit_scope.editable == ("x.py", "tests/x_test.py")
    assert plan.tasks[0].steps == ()
    assert plan.tasks[0].how_to_validate == ""
    assert any(d.task_id == "t2" and d.depends_on == "t1" for d in plan.deps)


@pytest.mark.asyncio
async def test_planner_emits_plan_with_deterministic_task_ids():
    llm = FakeLLM({
        "tasks": [
            {
                "id": "t1",
                "title": "Add Google provider",
                "editable": ["src/provider/google.py"],
                "depends_on": [],
            },
            {
                "id": "t2",
                "title": "Wire provider selection",
                "editable": ["src/auth.py"],
                "depends_on": ["t1"],
            },
        ],
    })
    res = await Planner(llm, project_map=_map()).run(
        NodeContext(_state(), cancel=asyncio.Event())
    )

    plan = res.output
    assert plan.tasks[0].id == "t1"
    assert plan.tasks[1].id == "t2"
    assert plan.tasks[0].edit_scope.editable == ("src/provider/google.py",)
    assert plan.deps[0].task_id == "t2" and plan.deps[0].depends_on == "t1"


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


@pytest.mark.asyncio
async def test_planner_falls_back_to_request_when_requirement_absent():
    # Headless (FULL_AUTO) skips the interviewer, so state.requirement is None.
    # The planner must synthesize the requirement from the raw request instead of
    # asserting — the request text becomes the summary.
    state = SessionState(
        requirement=None,
        request=Request(raw_text="fix the broken __hash__", kind=RequestKind.ENGINEERING),
        understanding=CodeContext(candidates=()),
    )
    llm = FakeLLM({"tasks": [], "deps": []})
    await Planner(llm, project_map=_map()).run(NodeContext(state, cancel=asyncio.Event()))
    prompt = llm.seen_messages[-1]["content"]
    assert "REQUIREMENT:" in prompt
    assert "fix the broken __hash__" in prompt


@pytest.mark.asyncio
async def test_planner_file_plan_always_empty_in_new_schema():
    # file_plan is no longer emitted by the model; the planner always returns file_plan=().
    llm = FakeLLM({
        "tasks": [{"id": "t1", "title": "server", "editable": ["server.py"], "depends_on": []}],
    })
    res = await Planner(llm, project_map=_map()).run(
        NodeContext(_state(), cancel=asyncio.Event())
    )
    plan = res.output
    assert plan.file_plan == ()
    assert plan.tasks[0].edit_scope.editable == ("server.py",)


@pytest.mark.asyncio
async def test_planner_file_plan_defaults_empty_when_omitted():
    # Older-shaped payloads without file_plan must still parse.
    llm = FakeLLM({"tasks": [], "deps": []})
    res = await Planner(llm, project_map=_map()).run(
        NodeContext(_state(), cancel=asyncio.Event())
    )
    assert res.output.file_plan == ()


@pytest.mark.asyncio
async def test_planner_prompt_teaches_cohesion_not_behavior_split():
    llm = FakeLLM({"tasks": [], "deps": []})
    await Planner(llm, project_map=_map()).run(
        NodeContext(_state(), cancel=asyncio.Event())
    )
    system = llm.seen_messages[0]["content"].lower()
    assert "fewer" in system                   # bias to merge
    assert "merge" in system                   # explicit merge instruction
    assert "plan_md" in system                 # markdown-first design
