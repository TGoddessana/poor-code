import pytest

from poor_code.app import PoorCodeApp
from poor_code.domain.agent import Agent
from poor_code.domain.harness.driver import Driver
from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.route import route
from poor_code.domain.session.models import EditScope, Plan, Query, QueryKind, Task
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.ui.store import PlanSegment, QuerySegment
from tests.infra.fakes import (
    FakeContextLoader, FakeSettingsLoader, FakeSystemPromptComposer,
)
from tests.provider.fakes import FakeLLMClient


def _assembler():
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(), context_loader=FakeContextLoader(),
        prompt_composer=FakeSystemPromptComposer(), prompt_builder=PromptBuilder())


class _PlannerStub:
    """Sits at 'plan_gate': emits a Plan, routes to 'composer' (unregistered → park)."""
    name = "plan_gate"
    async def run(self, ctx):
        return NodeResult(output=Plan(tasks=(
            Task(id="t1", title="Add login", purpose="p",
                 edit_scope=EditScope(editable=("src/auth.py",)),
                 how_to_validate="pytest tests/auth"),
        )))


class _ConfirmPlanStub:
    name = "plan_confirm_gate"

    async def run(self, ctx):
        return NodeResult(query=Query(
            id="confirm_plan",
            kind=QueryKind.CONFIRM,
            prompt="Proceed with this plan?",
            options=("yes", "revise"),
        ))


def _make_driver(_llm, _on_step=None):
    reg = NodeRegistry()
    reg.register(_PlannerStub())
    return Driver(reg, route)


def _make_confirm_driver(_llm, _on_step=None):
    reg = NodeRegistry()
    reg.register(_ConfirmPlanStub())
    return Driver(reg, route)


def _app_at_plan_gate():
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=_assembler())
    return PoorCodeApp(agent=agent, make_driver=_make_driver)


def _app_at_plan_confirm_gate():
    agent = Agent(llm=FakeLLMClient.text_only("x"), tools=ToolRegistry([]),
                  assembler=_assembler())
    return PoorCodeApp(agent=agent, make_driver=_make_confirm_driver)


def _plan():
    return Plan(tasks=(
        Task(id="t1", title="Add login", purpose="p",
             edit_scope=EditScope(editable=("src/auth.py",)),
             how_to_validate="pytest tests/auth"),
    ))


@pytest.mark.asyncio
async def test_plan_park_renders_plan_segment():
    import asyncio
    from poor_code.domain.session.models import Cursor, Phase, Request, RequestKind, SessionState
    from poor_code.messages import TurnStarted
    from poor_code.ui.store import PromptSubmitted

    app = _app_at_plan_gate()
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        # Drive directly from plan_gate to avoid building the full router→planner
        # chain; this exercises the park→PlanReady rendering path specifically.
        app._turn_id = "T"
        app._turn_started = 0.0
        app._cancel = asyncio.Event()
        app.store.dispatch(PromptSubmitted(cmd_id="c", user_text="add login"))
        app.store.dispatch(TurnStarted(cmd_id="c", turn_id="T"))
        start = SessionState(
            cursor=Cursor(phase=Phase.PLANNING, current_node="plan_gate"),
            request=Request(raw_text="add login", kind=RequestKind.ENGINEERING))
        await app._drive(start)
        for _ in range(10):
            await pilot.pause()
        turn = app.store.state.turns[-1]
        plan_segs = [s for s in turn.segments if isinstance(s, PlanSegment)]
        assert plan_segs and "Add login" in plan_segs[0].lines[0]
        assert turn.status == "done"
        assert app.store.state.is_processing is False


@pytest.mark.asyncio
async def test_confirm_plan_query_renders_plan_segment_first():
    import asyncio
    from poor_code.domain.session.models import Cursor, Phase, Request, RequestKind, SessionState
    from poor_code.messages import TurnStarted
    from poor_code.ui.store import PromptSubmitted

    app = _app_at_plan_confirm_gate()
    async with app.run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        app._turn_id = "T"
        app._turn_started = 0.0
        app._cancel = asyncio.Event()
        app.store.dispatch(PromptSubmitted(cmd_id="c", user_text="add login"))
        app.store.dispatch(TurnStarted(cmd_id="c", turn_id="T"))
        start = SessionState(
            cursor=Cursor(phase=Phase.PLANNING, current_node="plan_confirm_gate"),
            request=Request(raw_text="add login", kind=RequestKind.ENGINEERING),
            plan=_plan(),
        )
        await app._drive(start)
        for _ in range(10):
            await pilot.pause()
        segs = app.store.state.turns[-1].segments
        plan_idx = next(i for i, s in enumerate(segs) if isinstance(s, PlanSegment))
        query_idx = next(i for i, s in enumerate(segs) if isinstance(s, QuerySegment))
        assert plan_idx < query_idx
        assert app.store.state.awaiting_input is True
