from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness import build_default_registry
from poor_code.domain.project_map.models import ProjectMap


class _LLM:
    async def stream(self, messages, tools, response_format=None):
        if False:
            yield None


def _map():
    return ProjectMap(version=2, generated_at=datetime.now(UTC),
                      cwd=Path("."), files=(), parse_errors=())


def test_default_interviewer_has_readonly_tools():
    reg = build_default_registry(llm=_LLM(), project_map=_map())
    interviewer = reg.get("interviewer")
    assert interviewer._tools is not None
    names = {t["function"]["name"] for t in interviewer._tools.schemas()}
    assert {"read", "grep", "glob", "list"} <= names
    assert "write" not in names and "edit" not in names and "bash" not in names
