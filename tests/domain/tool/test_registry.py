import pytest
from pydantic import BaseModel, Field

from poor_code.domain.tool.base import ExecuteResult
from poor_code.domain.tool.registry import ToolRegistry, DuplicateToolId


class _Args(BaseModel):
    path: str = Field(description="file path")


class _DummyTool:
    id = "dummy"
    description = "a dummy tool"
    params = _Args
    async def execute(self, args, ctx):
        return ExecuteResult(title="t", output="o")


def test_get_returns_tool_or_none():
    reg = ToolRegistry([_DummyTool()])
    assert reg.get("dummy").id == "dummy"
    assert reg.get("missing") is None


def test_schemas_emits_openai_function_shape():
    reg = ToolRegistry([_DummyTool()])
    schemas = reg.schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "dummy"
    assert s["function"]["description"] == "a dummy tool"
    params = s["function"]["parameters"]
    assert params["type"] == "object"
    assert "path" in params["properties"]


def test_duplicate_id_raises():
    with pytest.raises(DuplicateToolId, match="dummy"):
        ToolRegistry([_DummyTool(), _DummyTool()])
