import asyncio, json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.project_map.models import FileEntry, ProjectMap, Symbol, SymbolKind
from poor_code.domain.session.models import Request, RequestKind, SessionState
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.grep import GrepTool
from poor_code.provider.events import (
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted)


class ScriptedLLM:
    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls = []
    async def stream(self, messages, tools, response_format=None):
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


def _tool_round(name, args_json):
    return [
        ToolCallStarted(call_id="r1", name=name),
        ToolCallInputDelta(call_id="r1", json_delta=args_json),
        ToolCallEnded(call_id="r1"),
        FinishedReason(reason="tool_calls"),
    ]


def _map():
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(), parse_errors=())


def _tools():
    return ToolRegistry([ReadTool(), GrepTool()])


def _state():
    return SessionState(request=Request(raw_text="reconstruct image", kind=RequestKind.ENGINEERING))


def test_records_read_output_as_excerpt():
    ex = {}
    ExploringNode._maybe_record_excerpt("read", '{"path": "img.ppm"}', "P6 800 600 255", ex)
    assert ex["img.ppm"].text == "P6 800 600 255"
    assert ex["img.ppm"].truncated is False


def test_ignores_grep_and_tool_errors():
    ex = {}
    ExploringNode._maybe_record_excerpt("grep", '{"pattern": "x"}', "a match", ex)
    ExploringNode._maybe_record_excerpt("read", '{"path": "a"}', "ERROR: nope", ex)
    assert ex == {}


def test_truncates_long_read():
    ex = {}
    ExploringNode._maybe_record_excerpt("read", '{"path": "big"}', "x" * 5000, ex)
    assert ex["big"].truncated is True
    assert len(ex["big"].text) == 4000


def test_parse_maps_summary_and_excerpts():
    node = ExploringNode(ScriptedLLM([]), project_map=_map(), tools=_tools())
    from poor_code.domain.session.models import FileExcerpt
    cc = node.parse(
        json.dumps({"candidates": [], "confusers": [], "related_tests": [],
                    "grounding": "greenfield", "summary": "needs 800x600 ppm"}),
        excerpts=(FileExcerpt(path="img.ppm", text="P6 800 600"),),
    )
    assert cc.summary == "needs 800x600 ppm"
    assert cc.excerpts[0].path == "img.ppm"


def test_output_tool_exposes_summary():
    node = ExploringNode(ScriptedLLM([]), project_map=_map(), tools=_tools())
    props = node.output_tool()["function"]["parameters"]["properties"]
    assert "summary" in props


@pytest.mark.asyncio
async def test_read_during_explore_becomes_excerpt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "orig.sh").write_text("ffmpeg scale=800:600 reconstructed.ppm\n")
    llm = ScriptedLLM([
        _tool_round("read", json.dumps({"path": "orig.sh"})),     # ① read
        [TextDelta(text="seen"), FinishedReason(reason="stop")],  # ① stop
        _emit_round({"candidates": [], "confusers": [], "related_tests": [],
                     "grounding": "greenfield", "summary": "downsample to 800x600"}),
    ])
    node = ExploringNode(llm, project_map=_map(), tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert res.output.summary == "downsample to 800x600"
    assert any(e.path == "orig.sh" and "800:600" in e.text for e in res.output.excerpts)
