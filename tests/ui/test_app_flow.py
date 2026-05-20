import asyncio

from textual.widgets import Input

from poor_code.app import PoorCodeApp
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    TurnEnded,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
)


async def test_submit_routes_through_agent_and_updates_store():
    # ScriptedAgent reads the incoming cmd to set correlation IDs correctly.
    class ScriptedAgent:
        async def run(self, cmd, cancel):
            yield TurnStarted(cmd_id=cmd.cmd_id, turn_id="T1")
            yield AssistantTextDelta(turn_id="T1", text="hi ")
            yield AssistantTextDelta(turn_id="T1", text="there")
            yield AssistantMessageCompleted(turn_id="T1", text="hi there")
            yield UsageUpdated(turn_id="T1", input_tokens=2, output_tokens=2, cost_usd=0.0)
            yield TurnEnded(turn_id="T1")

    async with PoorCodeApp(agent=ScriptedAgent()).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("p", "i", "n", "g")
        await pilot.press("enter")
        # Drain worker; ScriptedAgent has no sleeps but the event loop needs to tick
        for _ in range(20):
            await pilot.pause()

        state = pilot.app.store.state
        assert len(state.turns) == 1
        turn = state.turns[0]
        assert turn.user_text == "ping"
        assert turn.turn_id == "T1"
        assert turn.status == "done"
        assert turn.assistant_text == "hi there"
        assert state.is_processing is False
        assert state.usage.input_tokens == 2
        assert state.usage.output_tokens == 2


async def test_cancel_during_turn_marks_failed():
    """Ctrl+C while processing sets _cancel; SlowAgent observes and stops."""

    class SlowAgent:
        async def run(self, cmd, cancel):
            yield TurnStarted(cmd_id=cmd.cmd_id, turn_id="T1")
            for _ in range(50):
                if cancel.is_set():
                    yield TurnFailed(turn_id="T1", error="cancelled")
                    return
                yield AssistantTextDelta(turn_id="T1", text=".")
                await asyncio.sleep(0.1)

    async with PoorCodeApp(agent=SlowAgent()).run_test() as pilot:
        await pilot.pause(); await pilot.pause()
        pilot.app.screen.query_one(Input).focus()
        await pilot.press("x")
        await pilot.press("enter")
        # Short explicit delay: enough for worker to start, not enough to finish
        await pilot.pause(delay=0.05)
        # Confirm we are processing
        assert pilot.app.store.state.is_processing is True
        # Trigger cancel
        pilot.app.action_cancel_or_quit()
        # Wait for agent to observe cancel and emit TurnFailed (at most one 0.1s sleep)
        for _ in range(20):
            await pilot.pause(delay=0.05)
        state = pilot.app.store.state
        assert state.is_processing is False
        assert state.turns[0].status == "failed"
        assert state.last_error == "cancelled"
