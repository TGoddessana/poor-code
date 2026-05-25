import asyncio
from pathlib import Path

import pytest

from poor_code.domain.agent import Agent
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.infra.prompt_builder import PromptBuilder
from poor_code.infra.turn_assembler import TurnAssembler
from poor_code.messages import (
    AssistantMessageCompleted,
    AssistantTextDelta,
    SendPrompt,
    TurnEnded,
    TurnStarted,
    UsageUpdated,
)
from poor_code.provider.events import (
    FinishedReason,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted as ProviderToolCallStarted,
)
from tests.infra.fakes import (
    FakeContextLoader,
    FakeSettingsLoader,
    FakeSystemPromptComposer,
    FakeTurnAssembler,
)
from tests.provider.fakes import FakeLLMClient


def _real_assembler_for_tests(
    user_block: str = "", system_block: str = "", system_text: str = "SYS"
) -> TurnAssembler:
    return TurnAssembler(
        settings_loader=FakeSettingsLoader(),
        context_loader=FakeContextLoader(
            user_block=user_block, system_block=system_block
        ),
        prompt_composer=FakeSystemPromptComposer(text=system_text),
        prompt_builder=PromptBuilder(),
    )


async def _collect(agent, cmd, cancel):
    return [ev async for ev in agent.run(cmd, cancel)]


@pytest.mark.asyncio
async def test_text_only_turn():
    llm = FakeLLMClient.text_only("hi there")
    agent = Agent(
        llm=llm, tools=ToolRegistry([]), assembler=_real_assembler_for_tests()
    )
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
    # The assembler may prepend its system message — verify the user payload only.
    sent_user = [m for m in llm.calls[0]["messages"] if m.get("role") == "user"]
    assert len(sent_user) == 1
    assert sent_user[0]["content"] == "ping"


@pytest.mark.asyncio
async def test_history_accumulates_across_turns():
    rounds = [
        [
            TextDelta(text="one"),
            FinishedReason(reason="stop"),
        ],
        [
            TextDelta(text="two"),
            FinishedReason(reason="stop"),
        ],
    ]
    llm = FakeLLMClient(rounds)
    agent = Agent(
        llm=llm, tools=ToolRegistry([]), assembler=_real_assembler_for_tests()
    )
    await _collect(agent, SendPrompt(text="A"), asyncio.Event())
    await _collect(agent, SendPrompt(text="B"), asyncio.Event())

    assert agent.history == [
        {"role": "user", "content": "A"},
        {"role": "assistant", "content": "one"},
        {"role": "user", "content": "B"},
        {"role": "assistant", "content": "two"},
    ]


from poor_code.domain.tool.base import ExecuteResult
from poor_code.domain.tool.read import ReadParams
from poor_code.messages import ToolCallFinished, ToolCallStarted as MsgToolCallStarted


class _FakeReadTool:
    id = "read"
    description = "fake"
    params = ReadParams

    def __init__(self, output: str = "FILE CONTENT") -> None:
        self.output = output
        self.calls: list[ReadParams] = []

    async def execute(self, args, ctx):
        self.calls.append(args)
        return ExecuteResult(title="t", output=self.output)


@pytest.mark.asyncio
async def test_tool_call_executed_then_followup_text():
    tool = _FakeReadTool(output="hello world")
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="read"),
            ToolCallInputDelta(call_id="c1", json_delta='{"path":"a.txt"}'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
        [
            TextDelta(text="done."),
            FinishedReason(reason="stop"),
        ],
    ]
    agent = Agent(
        llm=FakeLLMClient(rounds),
        tools=ToolRegistry([tool]),
        assembler=_real_assembler_for_tests(),
    )
    events = await _collect(agent, SendPrompt(text="read a.txt"), asyncio.Event())
    types = [type(e).__name__ for e in events]
    assert types == [
        "TurnStarted",
        "ToolCallStarted",
        "ToolCallFinished",
        "AssistantTextDelta",
        "AssistantMessageCompleted",
        "TurnEnded",
    ]
    assert tool.calls[0].path == "a.txt"
    # tool message + second user-less turn made it into history
    roles = [m["role"] for m in agent.history]
    assert roles == ["user", "assistant", "tool", "assistant"]


@pytest.mark.asyncio
async def test_tool_execute_error_yields_failed_and_recovers():
    class _Boom:
        id = "read"
        description = "fake"
        params = ReadParams
        async def execute(self, args, ctx):
            raise RuntimeError("disk full")
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="read"),
            ToolCallInputDelta(call_id="c1", json_delta='{"path":"a.txt"}'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
        [
            TextDelta(text="sorry"),
            FinishedReason(reason="stop"),
        ],
    ]
    agent = Agent(
        llm=FakeLLMClient(rounds),
        tools=ToolRegistry([_Boom()]),
        assembler=_real_assembler_for_tests(),
    )
    events = await _collect(agent, SendPrompt(text="x"), asyncio.Event())
    types = [type(e).__name__ for e in events]
    assert "ToolCallFailed" in types
    assert types[-1] == "TurnEnded"
    # tool error fed back to LLM
    tool_msg = next(m for m in agent.history if m["role"] == "tool")
    assert "disk full" in tool_msg["content"]


@pytest.mark.asyncio
async def test_unknown_tool_name_fails_gracefully():
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="no_such_tool"),
            ToolCallInputDelta(call_id="c1", json_delta='{}'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
        [
            TextDelta(text="ok"),
            FinishedReason(reason="stop"),
        ],
    ]
    agent = Agent(
        llm=FakeLLMClient(rounds),
        tools=ToolRegistry([]),
        assembler=_real_assembler_for_tests(),
    )
    events = await _collect(agent, SendPrompt(text="x"), asyncio.Event())
    types = [type(e).__name__ for e in events]
    assert "ToolCallFailed" in types
    assert types[-1] == "TurnEnded"


@pytest.mark.asyncio
async def test_invalid_args_json_fails_gracefully():
    tool = _FakeReadTool()
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="read"),
            ToolCallInputDelta(call_id="c1", json_delta='{not json'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
        [
            TextDelta(text="ok"),
            FinishedReason(reason="stop"),
        ],
    ]
    agent = Agent(
        llm=FakeLLMClient(rounds),
        tools=ToolRegistry([tool]),
        assembler=_real_assembler_for_tests(),
    )
    events = await _collect(agent, SendPrompt(text="x"), asyncio.Event())
    types = [type(e).__name__ for e in events]
    assert "ToolCallFailed" in types
    assert types[-1] == "TurnEnded"
    assert tool.calls == []  # never reached


@pytest.mark.asyncio
async def test_max_iterations_terminates_with_turn_ended():
    """Tool-call → tool-call → ... 10 rounds scripted. Loop is capped at 8."""
    from poor_code.domain.agent import MAX_ITERATIONS

    rounds = []
    for i in range(MAX_ITERATIONS + 2):
        cid = f"c{i}"
        rounds.append([
            ProviderToolCallStarted(call_id=cid, name="read"),
            ToolCallInputDelta(call_id=cid, json_delta='{"path":"a.txt"}'),
            ToolCallEnded(call_id=cid),
            FinishedReason(reason="tool_calls"),
        ])
    tool = _FakeReadTool()
    agent = Agent(
        llm=FakeLLMClient(rounds),
        tools=ToolRegistry([tool]),
        assembler=_real_assembler_for_tests(),
    )
    events = await _collect(agent, SendPrompt(text="loop"), asyncio.Event())
    # Did not crash, terminated with TurnEnded after exactly MAX_ITERATIONS LLM calls
    assert events[-1].__class__.__name__ == "TurnEnded"
    assert len(agent.llm.calls) == MAX_ITERATIONS


@pytest.mark.asyncio
async def test_cancel_before_first_iteration_yields_turn_failed():
    cancel = asyncio.Event()
    cancel.set()
    agent = Agent(
        llm=FakeLLMClient([]),
        tools=ToolRegistry([]),
        assembler=_real_assembler_for_tests(),
    )
    events = await _collect(agent, SendPrompt(text="x"), cancel)
    types = [type(e).__name__ for e in events]
    assert types[-1] == "TurnFailed"
    assert events[-1].error == "cancelled"


# --- TurnAssembler integration ------------------------------------------------


@pytest.mark.asyncio
async def test_agent_passes_assembled_messages_to_llm():
    llm = FakeLLMClient.text_only("ok")
    assembler = _real_assembler_for_tests(
        user_block="UCTX\n", system_block="SCTX\n", system_text="SYS_TEXT"
    )
    agent = Agent(llm=llm, tools=ToolRegistry([]), assembler=assembler)

    await _collect(agent, SendPrompt(text="hi"), asyncio.Event())

    sent = llm.calls[0]["messages"]
    assert sent[0] == {"role": "system", "content": "SYS_TEXT"}
    assert sent[1]["role"] == "user"
    assert sent[1]["content"] == "UCTX\nSCTX\nhi"


@pytest.mark.asyncio
async def test_history_never_contains_system_role():
    llm = FakeLLMClient.text_only("ok")
    agent = Agent(
        llm=llm, tools=ToolRegistry([]), assembler=_real_assembler_for_tests()
    )
    await _collect(agent, SendPrompt(text="hi"), asyncio.Event())

    assert all(m["role"] in {"user", "assistant", "tool"} for m in agent.history)


@pytest.mark.asyncio
async def test_assembler_receives_history_per_turn():
    fake_assembler = FakeTurnAssembler()
    llm = FakeLLMClient(
        rounds=[
            [TextDelta(text="A"), FinishedReason(reason="stop")],
            [TextDelta(text="B"), FinishedReason(reason="stop")],
        ]
    )
    agent = Agent(llm=llm, tools=ToolRegistry([]), assembler=fake_assembler)

    await _collect(agent, SendPrompt(text="one"), asyncio.Event())
    await _collect(agent, SendPrompt(text="two"), asyncio.Event())

    assert len(fake_assembler.calls) == 2
    assert fake_assembler.calls[1]["history"][0] == {"role": "user", "content": "one"}


@pytest.mark.asyncio
async def test_cancel_during_tool_execute_yields_tool_call_failed_then_turn_failed():
    from poor_code.domain.tool.base import ExecuteResult
    from poor_code.domain.tool.read import ReadParams
    from poor_code.messages import ToolCallFailed as MsgToolCallFailed, TurnFailed as MsgTurnFailed

    class _SlowTool:
        id = "read"
        description = "fake"
        params = ReadParams
        started: bool = False

        async def execute(self, args, ctx):
            _SlowTool.started = True
            await asyncio.sleep(10)
            return ExecuteResult(title="t", output="done")

    cancel = asyncio.Event()
    rounds = [
        [
            ProviderToolCallStarted(call_id="c1", name="read"),
            ToolCallInputDelta(call_id="c1", json_delta='{"path":"a.txt"}'),
            ToolCallEnded(call_id="c1"),
            FinishedReason(reason="tool_calls"),
        ],
    ]
    agent = Agent(
        llm=FakeLLMClient(rounds),
        tools=ToolRegistry([_SlowTool()]),
        assembler=_real_assembler_for_tests(),
    )

    collected: list = []

    async def run():
        async for ev in agent.run(SendPrompt(text="x"), cancel):
            collected.append(ev)

    run_task = asyncio.create_task(run())

    # tool이 시작될 때까지 대기 후 취소
    for _ in range(200):
        await asyncio.sleep(0.01)
        if _SlowTool.started:
            break
    cancel.set()

    await asyncio.wait_for(run_task, timeout=2.0)

    types = [type(e).__name__ for e in collected]
    assert "ToolCallFailed" in types
    assert "TurnFailed" in types

    tc_failed = next(e for e in collected if isinstance(e, MsgToolCallFailed))
    assert tc_failed.error == "cancelled"
    assert tc_failed.tool_call_id == "c1"

    turn_failed = next(e for e in collected if isinstance(e, MsgTurnFailed))
    assert turn_failed.error == "cancelled"

    # ToolCallFailed이 TurnFailed보다 먼저 와야 함
    assert types.index("ToolCallFailed") < types.index("TurnFailed")


# --- Task 3: TurnEnded with duration_sec + model, _compute_cost, UsageUpdated ---


def test_turn_ended_carries_duration_and_model():
    e = TurnEnded(turn_id="t1", duration_sec=1.25, model="gpt-4o")
    assert e.turn_id == "t1"
    assert e.duration_sec == 1.25
    assert e.model == "gpt-4o"


from poor_code.domain.agent import _compute_cost
from poor_code.provider.registry import ModelPricing


def test_compute_cost_with_pricing():
    p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
    # 1000 input @ $3/M + 500 output @ $15/M = 0.003 + 0.0075 = 0.0105
    cost = _compute_cost(p, 1000, 500)
    assert cost == pytest.approx(0.0105)


def test_compute_cost_none_pricing_returns_zero():
    assert _compute_cost(None, 1000, 500) == 0.0


def test_compute_cost_zero_tokens():
    p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
    assert _compute_cost(p, 0, 0) == 0.0


# --- Agent.run integration: UsageUpdated cost + TurnEnded duration/model ---


from poor_code.provider.events import UsageEnded


class _ModelAwareFakeLLM:
    """Streams a scripted list of LLMEvent values. .model lets the Agent
    resolve which model handled the turn."""

    def __init__(self, events, model: str = "claude-3-5-sonnet-20241022"):
        self._events = events
        self.model = model

    async def stream(self, messages, tools):
        for ev in self._events:
            yield ev


@pytest.mark.asyncio
async def test_agent_emits_usage_updated_with_cost():
    """Use a model that has non-zero pricing in the snapshot.
    claude-3-5-sonnet-20241022 = $3 input / $15 output per 1M."""
    # OpenAI's real SSE order: content deltas → finish_reason chunk → usage chunk.
    # UsageEnded arrives AFTER FinishedReason — the agent must keep consuming
    # the stream past FinishedReason to see it.
    events = [
        TextDelta(text="hello"),
        FinishedReason(reason="stop"),
        UsageEnded(input_tokens=1000, output_tokens=500),
    ]
    llm = _ModelAwareFakeLLM(events, model="claude-3-5-sonnet-20241022")
    agent = Agent(
        llm=llm, tools=ToolRegistry([]), assembler=_real_assembler_for_tests()
    )
    cancel = asyncio.Event()

    out_events = [ev async for ev in agent.run(SendPrompt(text="hi"), cancel)]

    usage_events = [e for e in out_events if isinstance(e, UsageUpdated)]
    assert len(usage_events) == 1
    u = usage_events[0]
    assert u.input_tokens == 1000
    assert u.output_tokens == 500
    # Expected: 1000 * 3 / 1e6 + 500 * 15 / 1e6 = 0.003 + 0.0075 = 0.0105
    assert u.cost_usd == pytest.approx(0.0105)


@pytest.mark.asyncio
async def test_agent_turn_ended_carries_duration_and_model():
    events = [
        TextDelta(text="hi"),
        FinishedReason(reason="stop"),
    ]
    llm = _ModelAwareFakeLLM(events, model="claude-3-5-sonnet-20241022")
    agent = Agent(
        llm=llm, tools=ToolRegistry([]), assembler=_real_assembler_for_tests()
    )
    cancel = asyncio.Event()

    end = None
    async for ev in agent.run(SendPrompt(text="hi"), cancel):
        if isinstance(ev, TurnEnded):
            end = ev
    assert end is not None
    assert end.model == "claude-3-5-sonnet-20241022"
    assert end.duration_sec >= 0.0  # monotonic guarantee
