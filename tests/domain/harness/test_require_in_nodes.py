import pytest

from poor_code.domain.session.models import SessionState, MissingInput
from poor_code.domain.harness.nodes.router import Router


class _LLM:
    async def stream(self, messages, tools, response_format=None):
        if False:
            yield None


def test_router_build_messages_missing_request_raises_missing_input():
    node = Router(_LLM())
    with pytest.raises(MissingInput):
        node.build_messages(SessionState())
