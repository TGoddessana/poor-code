import asyncio, pytest
from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.provisioner import Provisioner
from poor_code.domain.harness.steering import STEERING_HEADER
from poor_code.domain.session.models import Request, RequestKind, SessionState
from poor_code.domain.tool.registry import ToolRegistry
from tests.provider.fakes import FakeLLMClient


@pytest.mark.asyncio
async def test_provisioner_injects_steering(tmp_path):
    llm = FakeLLMClient.text_only("done")   # one round, no tool calls → loop exits
    node = Provisioner(llm, tmp_path, ToolRegistry([]))
    state = SessionState(
        request=Request(raw_text="fix x", kind=RequestKind.ENGINEERING),
        steering_notes=("use auth.py",))
    ctx = NodeContext(state=state, cancel=asyncio.Event())
    await node._provision(ctx)
    user_msgs = [m for m in llm.calls[0]["messages"] if m["role"] == "user"]
    assert any("use auth.py" in m["content"] for m in user_msgs)
    assert any(STEERING_HEADER in m["content"] for m in user_msgs)
