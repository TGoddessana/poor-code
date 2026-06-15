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
    FinishedReason, TextDelta, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)


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


def _fe(path, *, imported_by=(), symbols=()):
    return FileEntry(path=path, language="python", content_hash="h",
                     symbols=symbols, imports=(), imported_by=imported_by, tests=())


def _map(files):
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=tuple(files), parse_errors=())


def _tools():
    return ToolRegistry([ReadTool(), GrepTool()])


def _state():
    return SessionState(request=Request(raw_text="swap Input for TextArea",
                                        kind=RequestKind.ENGINEERING))


def test_map_digest_surfaces_imported_by():
    sym = Symbol(name="PromptBox", kind=SymbolKind.CLASS, lineno=1,
                 signature=None, doc=None, calls=(), called_by=())
    pmap = _map([_fe("ui/widgets/prompt_box.py", imported_by=("ui/app.py",), symbols=(sym,))])
    node = ExploringNode(ScriptedLLM([]), project_map=pmap, tools=_tools())
    digest = node._map_digest()
    assert "ui/widgets/prompt_box.py" in digest
    assert "ui/app.py" in digest
    assert "used by" in digest


def test_map_digest_omits_used_by_when_no_importers():
    pmap = _map([_fe("ui/app.py", imported_by=())])
    node = ExploringNode(ScriptedLLM([]), project_map=pmap, tools=_tools())
    assert "used by" not in node._map_digest()


def test_explore_prompt_has_receiver_rule():
    pmap = _map([_fe("ui/widgets/prompt_box.py", imported_by=("ui/app.py",))])
    node = ExploringNode(ScriptedLLM([]), project_map=pmap, tools=_tools())
    from poor_code.domain.harness.nodes.explorer import _EXPLORE_SYSTEM
    text = _EXPLORE_SYSTEM.lower()
    assert "receiver" in text or "1-hop" in text or "one hop" in text
    assert "import" in text


@pytest.mark.asyncio
async def test_pulls_unread_receiver_into_excerpts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prompt_box.py").write_text("class PromptBox:\n    pass\n")
    (tmp_path / "app.py").write_text(
        "from prompt_box import PromptBox\n"
        "class App:\n    def on_input_submitted(self): ...\n")
    llm = ScriptedLLM([
        _tool_round("read", json.dumps({"path": "prompt_box.py"})),
        [TextDelta(text="seen the widget"), FinishedReason(reason="stop")],
        _emit_round({"candidates": [{"file": "prompt_box.py", "symbol": "PromptBox"}],
                     "confusers": [], "related_tests": [], "search_notes": ""}),
    ])
    pmap = _map([
        _fe("prompt_box.py", imported_by=("app.py",)),
        _fe("app.py", imported_by=()),
    ])
    node = ExploringNode(llm, project_map=pmap, tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    paths = {e.path for e in res.output.excerpts}
    assert "prompt_box.py" in paths
    assert "app.py" in paths
    assert any(e.path == "app.py" and "on_input_submitted" in e.text
               for e in res.output.excerpts)


@pytest.mark.asyncio
async def test_does_not_reread_already_read_receiver(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prompt_box.py").write_text("class PromptBox: pass\n")
    (tmp_path / "app.py").write_text("from prompt_box import PromptBox\n")
    llm = ScriptedLLM([
        _tool_round("read", json.dumps({"path": "prompt_box.py"})),
        _tool_round("read", json.dumps({"path": "app.py"})),
        [TextDelta(text="done"), FinishedReason(reason="stop")],
        _emit_round({"candidates": [], "confusers": [], "related_tests": [],
                     "search_notes": ""}),
    ])
    pmap = _map([_fe("prompt_box.py", imported_by=("app.py",)), _fe("app.py")])
    node = ExploringNode(llm, project_map=pmap, tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    assert sum(1 for e in res.output.excerpts if e.path == "app.py") == 1


@pytest.mark.asyncio
async def test_hub_importers_are_not_pulled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "models.py").write_text("X = 1\n")
    hubbed_by = tuple(f"f{i}.py" for i in range(9))
    for name in hubbed_by:
        (tmp_path / name).write_text("from models import X\n")
    llm = ScriptedLLM([
        _tool_round("read", json.dumps({"path": "models.py"})),
        [TextDelta(text="seen"), FinishedReason(reason="stop")],
        _emit_round({"candidates": [], "confusers": [], "related_tests": [],
                     "search_notes": ""}),
    ])
    pmap = _map([_fe("models.py", imported_by=hubbed_by)]
                + [_fe(n) for n in hubbed_by])
    node = ExploringNode(llm, project_map=pmap, tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    paths = {e.path for e in res.output.excerpts}
    assert paths == {"models.py"}


@pytest.mark.asyncio
async def test_receiver_reads_are_capped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "child.py").write_text("class C: pass\n")
    parents = tuple(f"p{i}.py" for i in range(6))
    for name in parents:
        (tmp_path / name).write_text("from child import C\n")
    llm = ScriptedLLM([
        _tool_round("read", json.dumps({"path": "child.py"})),
        [TextDelta(text="seen"), FinishedReason(reason="stop")],
        _emit_round({"candidates": [], "confusers": [], "related_tests": [],
                     "search_notes": ""}),
    ])
    pmap = _map([_fe("child.py", imported_by=parents)] + [_fe(n) for n in parents])
    node = ExploringNode(llm, project_map=pmap, tools=_tools())
    res = await node.run(NodeContext(state=_state(), cancel=asyncio.Event()))
    pulled = [e.path for e in res.output.excerpts if e.path != "child.py"]
    assert len(pulled) == 4


@pytest.mark.asyncio
async def test_pull_receivers_stops_when_cancelled(tmp_path, monkeypatch):
    from poor_code.domain.session.models import FileExcerpt
    from poor_code.domain.tool.base import ToolContext, allow_all
    monkeypatch.chdir(tmp_path)
    (tmp_path / "child.py").write_text("class C: pass\n")
    (tmp_path / "parent.py").write_text("from child import C\n")
    excerpts = {"child.py": FileExcerpt(path="child.py", text="class C: pass")}
    pmap = _map([_fe("child.py", imported_by=("parent.py",)), _fe("parent.py")])
    node = ExploringNode(ScriptedLLM([]), project_map=pmap, tools=_tools())
    cancel = asyncio.Event()
    cancel.set()
    tool_ctx = ToolContext(turn_id="t", cancel=cancel, cwd=tmp_path, ask=allow_all)
    await node._pull_receivers(excerpts, tool_ctx,
                               NodeContext(state=_state(), cancel=cancel))
    assert "parent.py" not in excerpts


def test_interviewer_has_only_its_output_tool():
    from poor_code.domain.harness.nodes.interviewer import Interviewer
    pmap = _map([])
    node = Interviewer(ScriptedLLM([]), project_map=pmap)
    tool = node.output_tool()
    assert tool["function"]["name"] == "interview_step"
    # constructed without a tools arg → no working-tool registry (its only tool is
    # the output tool). The read-only registry is injected by build_default_registry.
    assert node._tools is None
