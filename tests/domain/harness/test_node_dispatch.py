import asyncio

import pytest
from pydantic import BaseModel

from poor_code.domain.harness.node import (
    AgentNode, NodeContext, strip_code_fence,
)
from poor_code.provider.events import FinishedReason, TextDelta


def test_strip_code_fence_unwraps_json_block():
    raw = '```json\n{"file_plan": [], "tasks": []}\n```'
    assert strip_code_fence(raw) == '{"file_plan": [], "tasks": []}'


def test_strip_code_fence_slices_leading_prose():
    raw = 'Here is the plan:\n{"tasks": []}\nThanks!'
    assert strip_code_fence(raw) == '{"tasks": []}'


def test_strip_code_fence_passthrough_plain_json():
    assert strip_code_fence('{"a": 1}') == '{"a": 1}'


class _Out(BaseModel):
    a: int = 0


class _FencingLLM:
    """Replies with the structured object as FENCED CONTENT (no tool call) — the
    exact failure mode from the gemma4 log."""
    async def stream(self, messages, tools, response_format=None):
        yield TextDelta(text='```json\n{"a": 7}\n```')
        yield FinishedReason(reason="stop")


class _FenceNode(AgentNode):
    name = "fencenode"

    def build_messages(self, state):
        return [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]

    def output_tool(self):
        return {"type": "function", "function": {"name": "emit", "parameters": {}}}

    def output_model(self):
        return _Out

    def parse(self, args_json):
        return _Out.model_validate_json(args_json)


@pytest.mark.asyncio
async def test_dispatch_recovers_fenced_content():
    node = _FenceNode(_FencingLLM())
    ctx = NodeContext(state=object(), cancel=asyncio.Event())
    result = await node.run(ctx)
    assert result.output.a == 7


class _LabelRecordingLLM:
    """A meter-bearing client that records the active_label at stream time, the way
    the real LLMClient attributes usage per node."""
    def __init__(self):
        self.active_label = None
        self.seen_label = "<unset>"

    async def stream(self, messages, tools, response_format=None):
        self.seen_label = self.active_label
        yield TextDelta(text='```json\n{"a": 1}\n```')
        yield FinishedReason(reason="stop")


@pytest.mark.asyncio
async def test_agent_node_tags_client_with_its_name():
    llm = _LabelRecordingLLM()
    node = _FenceNode(llm)
    await node.run(NodeContext(state=object(), cancel=asyncio.Event()))
    assert llm.seen_label == "fencenode"


import json
from poor_code.domain.harness.node import _example_from_schema


def test_example_from_schema_covers_required_and_enum():
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"enum": ["advance", "repair_impl", "repair_plan"]},
            "hint": {"type": "string"},
            "tasks": {"type": "array", "items": {"type": "object",
                       "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        },
        "required": ["verdict", "tasks"],
    }
    example = _example_from_schema(schema)
    data = json.loads(example)               # valid JSON
    assert data["verdict"] == "advance"       # first enum value
    assert isinstance(data["tasks"], list) and data["tasks"]
    assert data["tasks"][0]["id"] == "..."    # nested required filled


from poor_code.domain.harness.node import _retry_nudge, StructuredOutputError


def test_retry_nudge_includes_raw_schema_and_example():
    err = StructuredOutputError("validator", '{"verdict": "BAD"}', "verdict: invalid")
    schema = {"type": "object",
              "properties": {"verdict": {"enum": ["advance", "repair_impl"]}},
              "required": ["verdict"]}
    msg = _retry_nudge(err, schema=schema, example='{"verdict": "advance"}')
    assert '{"verdict": "BAD"}' in msg          # (a) the rejected output
    assert "advance" in msg                       # (b) the schema/enum
    assert '{"verdict": "advance"}' in msg        # (c) the example
