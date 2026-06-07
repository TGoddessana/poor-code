from poor_code.domain.harness.render_md import render_spec_md, render_plan_md
from poor_code.domain.session.models import (
    Requirement, AcceptanceSpec, AcceptanceCheck, Plan, Task, EditScope, Dependency)


def test_render_spec_md_has_requirement_and_checks():
    md = render_spec_md(Requirement(summary="build fib", acceptance=("n=10->55",)),
                        AcceptanceSpec(checks=(AcceptanceCheck("n=10->55", "curl ..."),)))
    assert "build fib" in md and "n=10->55" in md and "curl" in md


def test_render_plan_md_passthrough_with_skeleton():
    plan = Plan(plan_md="## t1: server.py — handler",
                tasks=(Task(id="t1", title="h", purpose="", edit_scope=EditScope(editable=("server.py",))),),
                deps=())
    md = render_plan_md(plan)
    assert "## t1" in md and "server.py" in md


def test_render_spec_md_includes_out_of_scope_and_assumptions():
    md = render_spec_md(
        Requirement(summary="g", out_of_scope=("no auth",), assumptions=("python3.14",)),
        None)
    assert "no auth" in md and "python3.14" in md


def test_render_plan_md_appends_deps():
    plan = Plan(plan_md="body", deps=(Dependency(task_id="t2", depends_on="t1"),))
    md = render_plan_md(plan)
    assert "t2<-t1" in md
