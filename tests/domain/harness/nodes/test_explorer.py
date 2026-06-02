import asyncio, json
import pytest
from datetime import UTC, datetime
from pathlib import Path
from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.session.models import SessionState, Request, RequestKind, CodeContext
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
    # stage ① stub makes NO stream call, so the only scripted round is the
    # stage ② extraction emit.
    llm = ScriptedLLM([
        _emit_round({"candidates": [{"file": "src/registry.py", "symbol": "build_provider"}],
                     "confusers": [], "related_tests": [], "search_notes": ""}),
    ])
    node = ExploringNode(llm, project_map=_map(), tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert isinstance(res.output, CodeContext)
    assert res.output.candidates[0].symbol == "build_provider"


@pytest.mark.asyncio
async def test_explorer_output_tool_has_search_notes():
    node = ExploringNode(ScriptedLLM([]), project_map=_map(), tools=_tools())
    props = node.output_tool()["function"]["parameters"]["properties"]
    assert {"candidates", "confusers", "related_tests", "search_notes"} <= set(props)
