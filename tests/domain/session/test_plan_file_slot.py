from poor_code.domain.session.models import Dependency, FileSlot, Plan, Task


def test_plan_defaults_file_plan_to_empty():
    assert Plan().file_plan == ()


def test_plan_carries_file_slots():
    plan = Plan(
        tasks=(Task(id="t1", title="server", purpose="serve"),),
        deps=(),
        file_plan=(FileSlot(path="server.py", responsibility="HTTP server on :3000"),),
    )
    assert plan.file_plan[0].path == "server.py"
    assert plan.file_plan[0].responsibility == "HTTP server on :3000"


def test_file_slot_responsibility_defaults_empty():
    assert FileSlot(path="x.py").responsibility == ""
