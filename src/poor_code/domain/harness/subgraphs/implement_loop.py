"""implement_loop — task 실행 루프를 하나의 CompiledGraph(서브그래프)로 접는다.
공유 스코프: plan/understanding 등 data 를 부모와 공유, cursor 만 격리.
IMPLEMENTATION repair 는 내부에서 처리(implementer 로), 그 외 layer 의 repair 는
바깥으로 bubble. 정상 종료(task_selector 'done')는 exit_branch='done' 으로 신호."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from poor_code.domain.harness.graph import CompiledGraph, EdgeTable, Graph
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.harness.nodes.composer import Composer
from poor_code.domain.harness.nodes.execution import TaskSelector, EngGate
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.harness.nodes.verifier import VerifierNode
from poor_code.domain.session.models import (
    AcceptanceSpec, CodeContext, Cursor, Layer, Phase, Plan, Requirement,
)
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.edit import EditTool
from poor_code.domain.tool.write import WriteTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.grep import GrepTool
from poor_code.domain.tool.glob import GlobTool
from poor_code.domain.tool.list import ListTool
from poor_code.domain.tool.registry import ToolRegistry

# inner forward edges. Verification v2: the deterministic bash-check chain (validator →
# validation_runner → completion_gate / failure_analyst) is replaced by a SINGLE
# observation-grounded adversarial Verifier (nodes/verifier.py). It drives+observes the
# work and emits the completion verdict directly — there is no model-authored bash
# acceptance command run as an absolute floor anymore.
# DRIFT WARNING: these rows are internal to this subgraph; route.FORWARD does not carry
# them. Change an execution-layer edge HERE.
_INNER_FORWARD = {
    ("task_selector", "task"): "composer",
    ("composer", None): "implementer",
    ("implementer", None): "eng_gate",
    ("eng_gate", None): "verifier",
    ("verifier", "done"): "task_selector",
}


def _implementer_tools() -> ToolRegistry:
    """The implementer's toolset. It writes/edits/runs (write/edit/bash) AND reads/
    searches structurally (read/grep/glob/list) — same read tools the explorer has,
    so it never has to `cat` whole files through bash."""
    return ToolRegistry([
        WriteTool(), EditTool(), BashTool(),
        ReadTool(), GrepTool(), GlobTool(), ListTool(),
    ])


def _verifier_tools() -> ToolRegistry:
    """The verifier OBSERVES — it runs and inspects but never mutates: bash to drive the
    work (start servers, curl, feed inputs) + read/grep/glob/list to inspect. No
    write/edit, so verification can't accidentally 'fix' what it is judging."""
    return ToolRegistry([
        BashTool(), ReadTool(), GrepTool(), GlobTool(), ListTool(),
    ])


def build_implement_loop(*, llm, cwd) -> CompiledGraph:
    cwd = Path(cwd)   # Implementer/Verifier expect a Path (build_default_registry passes project_map.cwd)
    reg = NodeRegistry()
    reg.register(TaskSelector())
    reg.register(Composer())
    reg.register(Implementer(llm, cwd=cwd, tools=_implementer_tools()))
    reg.register(EngGate())
    # Verification v2: one observation-grounded adversarial verifier replaces the whole
    # validator→validation_runner→failure_analyst→completion_judge bash-check chain.
    reg.register(VerifierNode(llm, cwd=cwd, tools=_verifier_tools()))
    edges = EdgeTable(
        forward=_INNER_FORWARD,
        back_edges={Layer.IMPLEMENTATION: "implementer"},
    )
    graph = Graph(nodes=reg, edges=edges, entry="task_selector")

    def fork(parent):
        # shared scope: keep all data, isolate cursor at the loop entry
        return replace(parent, cursor=Cursor(
            phase=Phase.IMPLEMENTING, current_node="task_selector",
            task_id=parent.cursor.task_id if parent.cursor is not None else None))

    def merge(parent, child):
        # adopt child's data (plan with new attempts etc.), restore parent's cursor
        return replace(child, cursor=parent.cursor)

    def exit_branch(child):
        # the loop only terminates normally when task_selector chose 'done'
        # (every other node forwards onward); signal 'done' to the outer graph.
        return "done"

    compiled = CompiledGraph(graph, name="implement_loop",
                             fork=fork, merge=merge, exit_branch=exit_branch,
                             phase=Phase.IMPLEMENTING)
    # Node I/O contract for the top-level coverage check: the loop cannot start without
    # a Plan (task_selector), and its implementer/verifier consume the binding spec.
    compiled.requires = (Plan, Requirement, CodeContext, AcceptanceSpec)
    compiled.produces = ()
    return compiled
