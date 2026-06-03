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


def test_execution_agent_nodes_are_registered():
    from poor_code.domain.harness import build_default_registry
    from datetime import datetime, UTC
    from pathlib import Path
    from poor_code.domain.project_map.models import ProjectMap

    class _LLM:
        async def stream(self, messages, tools, response_format=None):
            if False:
                yield None

    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    reg = build_default_registry(llm=_LLM(), project_map=pm)
    for name in ("composer", "implementer", "validator",
                 "failure_analyst", "global_validator"):
        assert reg.get(name) is not None, f"{name} not registered"


def test_reporter_is_registered():
    from datetime import UTC, datetime
    from pathlib import Path
    from poor_code.domain.harness import build_default_registry
    from poor_code.domain.project_map.models import ProjectMap

    class _LLM:
        async def stream(self, messages, tools, response_format=None):
            if False:
                yield None

    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    reg = build_default_registry(llm=_LLM(), project_map=pm)
    assert reg.get("reporter") is not None
    assert reg.get("reporter").name == "reporter"
