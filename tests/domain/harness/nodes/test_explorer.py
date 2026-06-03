import asyncio, json
import pytest
from datetime import UTC, datetime
from pathlib import Path
from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.session.models import (
    SessionState, Request, RequestKind, CodeContext, GroundingStatus,
)
from poor_code.domain.project_map.models import ProjectMap, FileEntry, Symbol, SymbolKind
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.grep import GrepTool
from poor_code.provider.events import (
    TextDelta, ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)


class ScriptedLLM:
    """Multi-round LLM stub: pops one event list per stream() call."""
    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls = []
    async def stream(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        for ev in self._rounds.pop(0):
            yield ev


def _emit_round(args_obj):
    return [
        ToolCallStarted(call_id="o1", name="emit_code_context"),
        ToolCallInputDelta(call_id="o1", json_delta=json.dumps(args_obj)),
        ToolCallEnded(call_id="o1"),
        FinishedReason(reason="tool_calls"),
    ]


def _map():
    sym = Symbol(name="build_provider", kind=SymbolKind.FUNCTION, lineno=12,
                 signature="def build_provider(name)", doc=None, calls=(), called_by=())
    fe = FileEntry(path="src/registry.py", language="python", content_hash="h",
                   symbols=(sym,), imports=(), imported_by=(), tests=())
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(fe,), parse_errors=())


def _tools():
    return ToolRegistry([ReadTool(), GrepTool()])


def _state():
    return SessionState(request=Request(raw_text="add provider", kind=RequestKind.ENGINEERING))


@pytest.mark.asyncio
async def test_explorer_extracts_code_context():
    # ① explore loop ends immediately (no tool calls), then ② extraction emit.
    llm = ScriptedLLM([
        [TextDelta(text="enough"), FinishedReason(reason="stop")],
        _emit_round({"candidates": [{"file": "src/registry.py", "symbol": "build_provider"}],
                     "confusers": [], "related_tests": [], "search_notes": ""}),
    ])
    node = ExploringNode(llm, project_map=_map(), tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert isinstance(res.output, CodeContext)
    assert res.output.candidates[0].symbol == "build_provider"


@pytest.mark.asyncio
async def test_explorer_emits_greenfield_grounding():
    llm = ScriptedLLM([
        [TextDelta(text="empty workspace"), FinishedReason(reason="stop")],
        _emit_round({"candidates": [], "confusers": [], "related_tests": [],
                     "search_notes": "empty project", "grounding": "greenfield"}),
    ])
    node = ExploringNode(llm, project_map=_map(), tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.output.grounding is GroundingStatus.GREENFIELD


@pytest.mark.asyncio
async def test_explorer_grounding_defaults_to_not_found_when_omitted():
    llm = ScriptedLLM([
        [TextDelta(text="searched"), FinishedReason(reason="stop")],
        _emit_round({"candidates": [], "confusers": [], "related_tests": [],
                     "search_notes": "nothing"}),  # no grounding key
    ])
    node = ExploringNode(llm, project_map=_map(), tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.output.grounding is GroundingStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_explorer_output_tool_exposes_grounding():
    node = ExploringNode(ScriptedLLM([]), project_map=_map(), tools=_tools())
    props = node.output_tool()["function"]["parameters"]["properties"]
    assert "grounding" in props


@pytest.mark.asyncio
async def test_explorer_output_tool_has_search_notes():
    node = ExploringNode(ScriptedLLM([]), project_map=_map(), tools=_tools())
    props = node.output_tool()["function"]["parameters"]["properties"]
    assert {"candidates", "confusers", "related_tests", "search_notes"} <= set(props)


def _tool_round(name, args_json):
    return [
        ToolCallStarted(call_id="t1", name=name),
        ToolCallInputDelta(call_id="t1", json_delta=args_json),
        ToolCallEnded(call_id="t1"),
        FinishedReason(reason="tool_calls"),
    ]


@pytest.mark.asyncio
async def test_explore_runs_grep_then_extracts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "registry.py").write_text("def build_provider(name):\n    return 1\n")
    llm = ScriptedLLM([
        _tool_round("grep", json.dumps({"pattern": "build_provider"})),  # ① round 1
        [TextDelta(text="found it"), FinishedReason(reason="stop")],       # ① round 2: stop
        _emit_round({"candidates": [{"file": "registry.py", "symbol": "build_provider"}],
                     "confusers": [], "related_tests": [], "search_notes": ""}),  # ②
    ])
    node = ExploringNode(llm, project_map=_map(), tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.output.candidates[0].symbol == "build_provider"
    # stage ② must have seen the grep tool result in its messages
    extract_msgs = llm.calls[-1]["messages"]
    assert any("build_provider" in str(m.get("content", "")) and m["role"] == "tool"
               for m in extract_msgs)


@pytest.mark.asyncio
async def test_explore_injects_repair_hint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "registry.py").write_text("x = 1\n")
    llm = ScriptedLLM([
        [TextDelta(text="ok"), FinishedReason(reason="stop")],   # ① stop immediately
        _emit_round({"candidates": [], "confusers": [], "related_tests": [],
                     "search_notes": "still nothing"}),
    ])
    state = SessionState(
        request=Request(raw_text="add provider", kind=RequestKind.ENGINEERING),
        repair_hint="grep 'provider' was empty; try registry/factory",
    )
    node = ExploringNode(llm, project_map=_map(), tools=_tools())
    await node.run(NodeContext(state=state, cancel=asyncio.Event()))
    seed_user = llm.calls[0]["messages"][1]["content"]   # stage ① user message
    assert "grep 'provider' was empty" in seed_user
