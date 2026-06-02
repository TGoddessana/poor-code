"""Smoke test: cli._build_agent() wires every dependency Agent needs."""
from __future__ import annotations

import asyncio

from poor_code.cli import _build_agent, _initial_llm, _start_session
from poor_code.messages import SendPrompt


async def test_build_agent_returns_runnable_agent(tmp_path, monkeypatch):
    # Force a no-provider boot by pointing auth_store at an empty home.
    monkeypatch.setenv("HOME", str(tmp_path))
    session = _start_session(tmp_path)
    agent = _build_agent(session, _initial_llm())

    assert agent.assembler is not None
    assert agent.llm is not None
    assert agent.tools is not None
    assert agent.session is session

    # Run a turn — NoAuthLLM raises in stream(), so we expect TurnFailed, not a crash.
    events = []
    async for ev in agent.run(SendPrompt(text="hi"), asyncio.Event()):
        events.append(type(ev).__name__)
    assert "TurnFailed" in events
