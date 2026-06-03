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


def test_initial_llm_uses_active_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from poor_code.infra import auth_store
    monkeypatch.setattr(auth_store.Path, "home", classmethod(lambda cls: tmp_path))
    auth_store.save("ollama_cloud", api_key="a", model="m1")
    auth_store.save("openai", api_key="sk", model="gpt-5.4-mini")  # active = openai

    llm = _initial_llm()
    assert llm.base_url == "https://api.openai.com"
    assert llm.model == "gpt-5.4-mini"


def test_initial_llm_falls_back_when_no_active(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from poor_code.infra import auth_store
    monkeypatch.setattr(auth_store.Path, "home", classmethod(lambda cls: tmp_path))
    # Write a providers entry with no top-level 'active' key.
    import json
    p = tmp_path / ".poor-code" / "auth.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(
        {"providers": {"ollama_cloud": {"api_key": "a", "model": "m1"}}}))

    llm = _initial_llm()
    assert llm.base_url == "https://ollama.com"


def test_initial_llm_noauth_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from poor_code.infra import auth_store
    monkeypatch.setattr(auth_store.Path, "home", classmethod(lambda cls: tmp_path))
    llm = _initial_llm()
    assert type(llm).__name__ == "NoAuthLLM"
