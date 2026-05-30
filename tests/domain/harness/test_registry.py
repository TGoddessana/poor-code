from poor_code.domain.harness.registry import NodeRegistry


class _N:
    def __init__(self, name): self.name = name
    async def run(self, ctx): ...


def test_register_and_get():
    reg = NodeRegistry()
    n = _N("locator")
    reg.register(n)
    assert reg.get("locator") is n


def test_get_missing_returns_none():
    assert NodeRegistry().get("nope") is None
