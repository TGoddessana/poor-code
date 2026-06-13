import asyncio
import json

import pytest

from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.global_validator import GlobalValidator
from poor_code.domain.session.models import (
    AcceptanceCheck, AcceptanceSpec, Plan, SessionState, Task, TaskStatus,
    VerdictKind,
)
from poor_code.provider.events import (
    FinishedReason, ToolCallEnded, ToolCallInputDelta, ToolCallStarted,
)


class _NoLLM:
    async def stream(self, messages, tools, response_format=None):
        if False:  # pragma: no cover — never yields; pass path must not dispatch
            yield None


class FakeLLM:
    async def stream(self, messages, tools, response_format=None):
        yield ToolCallStarted(call_id="c1", name=tools[0]["function"]["name"])
        yield ToolCallInputDelta(call_id="c1", json_delta=json.dumps({"hint": "fix it"}))
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _state(accept_cmd):
    task = Task(id="t1", title="t", purpose="p", how_to_validate="true",
                status=TaskStatus.DONE)
    return SessionState(
        plan=Plan(tasks=(task,)),
        acceptance=AcceptanceSpec(checks=(
            AcceptanceCheck(criterion="global", command=accept_cmd),)),
    )


@pytest.mark.asyncio
async def test_passes_when_acceptance_and_tasks_pass(tmp_path):
    gv = GlobalValidator(_NoLLM(), cwd=tmp_path)
    res = await gv.run(NodeContext(_state("true"), cancel=asyncio.Event()))
    assert res.branch == "pass"


@pytest.mark.skip(reason="v2: global_validator no longer runs bash acceptance checks (pass-through)")
@pytest.mark.asyncio
async def test_repairs_when_acceptance_check_fails(tmp_path):
    gv = GlobalValidator(FakeLLM(), cwd=tmp_path)
    # per-task `true` passes, but the global acceptance `false` fails → repair
    res = await gv.run(NodeContext(_state("false"), cancel=asyncio.Event()))
    assert res.verdict is not None
    assert res.verdict.kind in (VerdictKind.REPAIR, VerdictKind.ESCALATE)
