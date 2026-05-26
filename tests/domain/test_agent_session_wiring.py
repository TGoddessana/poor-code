"""Agent ↔ SessionService wiring.

Per S1 wiring decision:
- session=None must remain valid (test-friendly; existing 348 tests unchanged)
- First user message in a session opens a Task
- Subsequent messages in the same Agent instance are folded into that Task
- Agent does NOT end_task on TurnEnded — task ends only via future S9 signals
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from poor_code.domain.agent import Agent
from poor_code.domain.session import SessionService
from poor_code.domain.session.store import SessionStore
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.messages import SendPrompt
from poor_code.provider.events import FinishedReason, TextDelta
from tests.domain.test_agent import _real_assembler_for_tests
from tests.provider.fakes import FakeLLMClient


def _started_service(root: Path, cwd: Path) -> SessionService:
    svc = SessionService(SessionStore(root))
    svc.start_session(cwd)
    return svc


def _agent(llm, session=None) -> Agent:
    return Agent(
        llm=llm,
        tools=ToolRegistry([]),
        assembler=_real_assembler_for_tests(),
        session=session,
    )


async def _collect(agent, cmd):
    return [ev async for ev in agent.run(cmd, asyncio.Event())]


@pytest.mark.asyncio
async def test_agent_works_without_session(tmp_path: Path):
    """session=None: no disk writes, existing behavior preserved."""
    llm = FakeLLMClient.text_only("hi")
    agent = _agent(llm, session=None)
    await _collect(agent, SendPrompt(text="ping"))
    # No .poor-code/ directory created since no session was injected.
    assert not (tmp_path / ".poor-code").exists()


@pytest.mark.asyncio
async def test_agent_begins_task_on_first_message(tmp_path: Path):
    svc = _started_service(tmp_path / ".poor-code", tmp_path)
    assert svc.active_task() is None

    llm = FakeLLMClient.text_only("hi")
    agent = _agent(llm, session=svc)
    await _collect(agent, SendPrompt(text="add a flag"))

    task = svc.active_task()
    assert task is not None
    assert task.raw_request == "add a flag"
    # request.json must exist on disk.
    request_path = svc.task_dir(task.task_id) / "request.json"
    assert request_path.is_file()


@pytest.mark.asyncio
async def test_subsequent_messages_fold_into_same_task(tmp_path: Path):
    svc = _started_service(tmp_path / ".poor-code", tmp_path)
    rounds = [
        [TextDelta(text="one"), FinishedReason(reason="stop")],
        [TextDelta(text="two"), FinishedReason(reason="stop")],
    ]
    agent = _agent(FakeLLMClient(rounds), session=svc)

    await _collect(agent, SendPrompt(text="first"))
    first_task = svc.active_task()
    assert first_task is not None

    await _collect(agent, SendPrompt(text="second"))
    second_task = svc.active_task()
    assert second_task is not None
    assert second_task.task_id == first_task.task_id, (
        "second message must continue the same task, not open a new one"
    )


@pytest.mark.asyncio
async def test_agent_does_not_end_task_on_turn_ended(tmp_path: Path):
    """TurnEnded ≠ task done. V1 leaves the task open until a future S9 signal."""
    svc = _started_service(tmp_path / ".poor-code", tmp_path)
    agent = _agent(FakeLLMClient.text_only("done"), session=svc)
    await _collect(agent, SendPrompt(text="anything"))

    # Active task must still be live after the turn ends.
    assert svc.active_task() is not None
