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
