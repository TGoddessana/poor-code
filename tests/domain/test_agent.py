import asyncio

import pytest

from poor_code.domain.agent import Agent
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    SendPrompt,
    TurnEnded,
    TurnStarted,
)
from tests.provider.fakes import FakeLLMClient


async def _collect(agent, cmd, cancel):
    return [ev async for ev in agent.run(cmd, cancel)]


@pytest.mark.asyncio
async def test_text_only_turn():
    llm = FakeLLMClient.text_only("hi there")
    agent = Agent(llm=llm, tools=ToolRegistry([]))
    events = await _collect(agent, SendPrompt(text="ping"), asyncio.Event())

    types = [type(ev).__name__ for ev in events]
    assert types == [
        "TurnStarted",
        "AssistantTextDelta",
        "AssistantMessageCompleted",
        "TurnEnded",
    ]
    assert isinstance(events[1], AssistantTextDelta) and events[1].text == "hi there"
    assert isinstance(events[2], AssistantMessageCompleted) and events[2].text == "hi there"
    assert llm.calls[0]["messages"] == [{"role": "user", "content": "ping"}]


@pytest.mark.asyncio
async def test_history_accumulates_across_turns():
    rounds = [
        [
            # turn 1
            __import__("poor_code.provider.events", fromlist=["TextDelta"]).TextDelta(text="one"),
            __import__("poor_code.provider.events", fromlist=["FinishedReason"]).FinishedReason(reason="stop"),
        ],
        [
            # turn 2
            __import__("poor_code.provider.events", fromlist=["TextDelta"]).TextDelta(text="two"),
            __import__("poor_code.provider.events", fromlist=["FinishedReason"]).FinishedReason(reason="stop"),
        ],
    ]
    llm = FakeLLMClient(rounds)
    agent = Agent(llm=llm, tools=ToolRegistry([]))
    await _collect(agent, SendPrompt(text="A"), asyncio.Event())
    await _collect(agent, SendPrompt(text="B"), asyncio.Event())
    second_messages = llm.calls[1]["messages"]
    assert second_messages == [
        {"role": "user", "content": "A"},
        {"role": "assistant", "content": "one"},
        {"role": "user", "content": "B"},
    ]
