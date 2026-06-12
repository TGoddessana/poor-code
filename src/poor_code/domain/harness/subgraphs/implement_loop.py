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
from poor_code.domain.harness.nodes.execution import (
    TaskSelector, EngGate, ValidationRunner, CompletionGate,
)
from poor_code.domain.harness.nodes.implementer import Implementer
from poor_code.domain.harness.nodes.validator import Validator
from poor_code.domain.harness.nodes.failure_analyst import FailureAnalyst
from poor_code.domain.session.models import Cursor, Layer, Phase
from poor_code.domain.tool.bash import BashTool
from poor_code.domain.tool.edit import EditTool
from poor_code.domain.tool.write import WriteTool
from poor_code.domain.tool.read import ReadTool
from poor_code.domain.tool.grep import GrepTool
from poor_code.domain.tool.glob import GlobTool
from poor_code.domain.tool.list import ListTool
from poor_code.domain.tool.registry import ToolRegistry

# inner forward edges — copied verbatim from route.FORWARD for these nodes, EXCEPT
# ("task_selector","done") is intentionally absent so 'done' exits the subgraph.
# DRIFT WARNING: these rows are a hand-copy of the inner execution edges that USED to
# live in route.FORWARD. Those rows have been removed from route.FORWARD (they are now
# internal to this subgraph). If you change an execution-layer edge, change it HERE —
# route.FORWARD no longer carries it, so the two can silently drift apart.
_INNER_FORWARD = {
    ("task_selector", "task"): "composer",
    ("composer", None): "implementer",
    ("implementer", None): "eng_gate",
    ("eng_gate", None): "validator",
    ("validator", None): "validation_runner",
    ("validation_runner", "pass"): "completion_gate",
    ("validation_runner", "fail"): "failure_analyst",
    ("failure_analyst", None): "completion_gate",
    ("completion_gate", "done"): "task_selector",
}


def _implementer_tools() -> ToolRegistry:
    """The implementer's toolset. It writes/edits/runs (write/edit/bash) AND reads/
    searches structurally (read/grep/glob/list) — same read tools the explorer has,
    so it never has to `cat` whole files through bash."""
    return ToolRegistry([
        WriteTool(), EditTool(), BashTool(),
        ReadTool(), GrepTool(), GlobTool(), ListTool(),
    ])


def build_implement_loop(*, llm, cwd) -> CompiledGraph:
    cwd = Path(cwd)   # Implementer/ValidationRunner expect a Path (build_default_registry passes project_map.cwd)
    reg = NodeRegistry()
    reg.register(TaskSelector())
    reg.register(Composer())
    reg.register(Implementer(llm, cwd=cwd, tools=_implementer_tools()))
    reg.register(EngGate())
    reg.register(Validator(llm, cwd=cwd))
    reg.register(ValidationRunner(cwd=cwd))
    reg.register(FailureAnalyst(llm))
    reg.register(CompletionGate())
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

    return CompiledGraph(graph, name="implement_loop",
                         fork=fork, merge=merge, exit_branch=exit_branch,
                         phase=Phase.IMPLEMENTING)
