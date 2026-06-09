from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.session.models import EditScope, SessionState, Task
from poor_code.domain.tool.registry import ToolRegistry
from tests.provider.fakes import FakeLLMClient


def test_implementer_prompt_includes_steering(tmp_path):
    node = Implementer(FakeLLMClient.text_only("x"), tmp_path, ToolRegistry([]))
    task = Task(
        id="t1", title="do thing", purpose="because",
        edit_scope=EditScope(editable=("a.py",)),
        how_to_validate="pytest -q",
    )
    state = SessionState(steering_notes=("write tests first",))
    assert state.plan is None
    assert "write tests first" in node._prompt(state, task)
