import asyncio
import pytest
from poor_code.domain.harness.node import NodeContext
from poor_code.domain.harness.nodes.router import Router
from poor_code.domain.session.models import SessionState, Request, RequestKind


def _state(text):
    return SessionState(request=Request(raw_text=text, kind=RequestKind.ENGINEERING))


@pytest.mark.asyncio
@pytest.mark.parametrize("text,kind", [
    ("add oauth login to the api", RequestKind.ENGINEERING),
    ("refactor the parser", RequestKind.ENGINEERING),
    ("hi there", RequestKind.LIGHTWEIGHT),
    ("thanks!", RequestKind.LIGHTWEIGHT),
    ("", RequestKind.LIGHTWEIGHT),
])
async def test_router_classifies(text, kind):
    node = Router()
    res = await node.run(NodeContext(state=_state(text), cancel=asyncio.Event()))
    assert isinstance(res.output, Request)
    assert res.output.kind is kind
    assert res.output.raw_text == text
