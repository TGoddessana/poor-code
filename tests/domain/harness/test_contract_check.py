from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness.contracts import contract_warnings
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness import build_default_registry
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.session.models import Request, Plan


class _Producer:
    name = "producer"
    requires = ()
    produces = (Request,)


class _ConsumerOK:
    name = "consumer_ok"
    requires = (Request,)
    produces = ()


class _ConsumerMissing:
    name = "consumer_missing"
    requires = (Plan,)   # nobody produces Plan in this registry
    produces = ()


class _LLM:
    async def stream(self, messages, tools, response_format=None):
        if False:
            yield None


def _map():
    return ProjectMap(version=2, generated_at=datetime.now(UTC),
                      cwd=Path("."), files=(), parse_errors=())


def test_covered_requirement_yields_no_warning():
    reg = NodeRegistry()
    reg.register(_Producer())
    reg.register(_ConsumerOK())
    assert contract_warnings(reg) == []


def test_uncovered_requirement_is_flagged():
    reg = NodeRegistry()
    reg.register(_Producer())
    reg.register(_ConsumerMissing())
    warnings = contract_warnings(reg)
    assert len(warnings) == 1
    assert "consumer_missing" in warnings[0]
    assert "Plan" in warnings[0]


def test_default_registry_has_no_contract_warnings():
    reg = build_default_registry(llm=_LLM(), project_map=_map())
    assert contract_warnings(reg) == []
