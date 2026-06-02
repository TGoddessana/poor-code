from datetime import UTC, datetime
from pathlib import Path
from poor_code.domain.harness import build_default_registry
from poor_code.domain.project_map.models import ProjectMap


class _Agent:
    llm = None
    async def run(self, cmd, cancel):
        if False:
            yield None


def _empty_map():
    return ProjectMap(version=2, generated_at=datetime.now(UTC),
                      cwd=Path("."), files=(), parse_errors=())


def test_fast_path_registered_when_agent_provided():
    reg = build_default_registry(llm=object(), project_map=_empty_map(), agent=_Agent())
    assert reg.get("fast_path") is not None
    assert reg.get("fast_path").name == "fast_path"


def test_fast_path_absent_without_agent():
    reg = build_default_registry(llm=object(), project_map=_empty_map())
    assert reg.get("fast_path") is None
