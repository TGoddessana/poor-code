import asyncio
import json
import pytest
from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.locator import Locator
from poor_code.domain.session.models import SessionState, Request, RequestKind, CodeContext
from poor_code.domain.project_map.models import ProjectMap, FileEntry, Symbol, SymbolKind
from poor_code.provider.events import (
    ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason,
)
from datetime import UTC, datetime
from pathlib import Path


class FakeLLMClient:
    """Substitutes at the LLMClient boundary. Emits one tool call whose args
    JSON is the canned structured output, then finishes."""
    def __init__(self, args_obj):
        self._args = json.dumps(args_obj)

    async def stream(self, messages, tools, response_format=None):
        # the node must have offered exactly one output tool
        assert len(tools) == 1
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=self._args)
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _project_map():
    sym = Symbol(name="login", kind=SymbolKind.FUNCTION, lineno=10,
                 signature="def login()", doc=None, calls=(), called_by=())
    fe = FileEntry(path="src/auth.py", language="python", content_hash="h",
                   symbols=(sym,), imports=(), imported_by=(), tests=())
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(fe,), parse_errors=())


@pytest.mark.asyncio
async def test_locator_produces_code_context_from_structured_output():
    llm = FakeLLMClient({
        "candidates": [{"file": "src/auth.py", "symbol": "login", "lineno": 10}],
        "confusers": [{"file": "src/profile.py"}],
        "related_tests": [{"file": "tests/test_auth.py"}],
    })
    node = Locator(llm, project_map=_project_map())
    state = SessionState(request=Request(raw_text="fix login", kind=RequestKind.ENGINEERING))
    res = await node.run(NodeContext(state=state, cancel=asyncio.Event()))

    assert isinstance(res.output, CodeContext)
    assert res.output.candidates[0].file == "src/auth.py"
    assert res.output.candidates[0].symbol == "login"
    assert res.output.confusers[0].symbol is None
    assert res.output.related_tests[0].file == "tests/test_auth.py"


@pytest.mark.asyncio
async def test_locator_output_tool_schema_names_the_fields():
    node = Locator(FakeLLMClient({"candidates": [], "confusers": [], "related_tests": []}),
                   project_map=_project_map())
    tool = node.output_tool()
    props = tool["function"]["parameters"]["properties"]
    assert {"candidates", "confusers", "related_tests"} <= set(props)
