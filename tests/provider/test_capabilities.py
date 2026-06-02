from poor_code.provider.capabilities import Capabilities
from poor_code.provider.route import Route


def test_capabilities_conservative_defaults():
    c = Capabilities()
    assert c.response_format is False
    assert c.tool_choice is False
    assert c.parallel_tool_calls is False
    assert c.strict_tools is False


def test_capabilities_explicit():
    c = Capabilities(response_format=True)
    assert c.response_format is True and c.tool_choice is False


def test_route_has_default_capabilities():
    class _P:
        def build_body(self, *a, **k): return {}
        def for_stream(self): return self
        def parse_chunk(self, chunk): return []
    from poor_code.provider.auth import BearerAuth
    from poor_code.provider.framing import SseFraming
    r = Route(protocol=_P(), endpoint="/x", auth=BearerAuth(token="t"), framing=SseFraming())
    assert r.capabilities == Capabilities()
