import asyncio

from poor_code.domain.echo_agent import EchoAgent
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    SendPrompt,
    TurnEnded,
    TurnStarted,
)


async def _drain(agent, cmd, cancel):
    return [ev async for ev in agent.run(cmd, cancel)]


async def test_echo_agent_yields_expected_event_sequence():
    agent = EchoAgent()
    cmd = SendPrompt(text="hello")
    cancel = asyncio.Event()
    events = await _drain(agent, cmd, cancel)

    types = [type(e).__name__ for e in events]
    assert types[0] == "TurnStarted"
    assert types[-1] == "TurnEnded"
    # At least one delta and one completed in between
    assert any(isinstance(e, AssistantTextDelta) for e in events)
    assert any(isinstance(e, AssistantMessageCompleted) for e in events)


async def test_echo_agent_uses_same_turn_id_across_events():
    agent = EchoAgent()
    cmd = SendPrompt(text="hi")
    events = [ev async for ev in agent.run(cmd, asyncio.Event())]
    turn_started = next(e for e in events if isinstance(e, TurnStarted))
    assert turn_started.cmd_id == cmd.cmd_id
    for e in events[1:]:
        assert getattr(e, "turn_id") == turn_started.turn_id


async def test_echo_agent_completed_text_contains_input():
    agent = EchoAgent()
    events = [ev async for ev in agent.run(SendPrompt(text="ping"), asyncio.Event())]
    final = next(e for e in events if isinstance(e, AssistantMessageCompleted))
    assert "ping" in final.text


async def test_echo_agent_respects_cancel_between_yields():
    agent = EchoAgent()
    cancel = asyncio.Event()
    cancel.set()  # cancel before we even start
    events = [ev async for ev in agent.run(SendPrompt(text="x"), cancel)]
    assert events[-1].__class__.__name__ == "TurnFailed"
