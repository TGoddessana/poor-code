"""Graph — (nodes + edges + entry) 의 1급 객체. EdgeTable 은 그래프별 토폴로지.
전역 route() 를 대체하되, 진입 그래프에선 동일 동작을 보존한다 (다음 태스크에서 배선)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import Layer, SessionState, VerdictKind


Fork = Callable[[SessionState], SessionState]
Merge = Callable[[SessionState, SessionState], SessionState]
ExitBranch = Callable[[SessionState], "str | None"]


class _Escape:
    """이 그래프엔 목적지가 없음 — verdict 를 바깥 그래프로 bubble 하라는 표식."""
    __slots__ = ()
    def __repr__(self) -> str: return "ESCAPE"


ESCAPE = _Escape()

# route() returns the next node name, None (terminal stop), or ESCAPE (bubble to outer graph).
RouteResult = str | None | _Escape


@dataclass(frozen=True)
class Rewrite:
    """정책 조건부 엣지 재작성 (예: FULL_AUTO 에서 interviewer skip)."""
    when: Callable[[SessionState], bool]
    # remap is a dict (unhashable) — Rewrite is held only inside a tuple, never hashed.
    remap: dict[str, str]   # 다음 노드 이름 → 대체 이름

    def apply(self, nxt: str | None, state: SessionState) -> str | None:
        if nxt is not None and self.when(state):
            return self.remap.get(nxt, nxt)
        return nxt


@dataclass(frozen=True)
class EdgeTable:
    forward: dict[tuple[str, str | None], str]
    back_edges: dict[Layer, str]
    rewrites: tuple[Rewrite, ...] = ()

    def route(self, node: str, result: NodeResult, state: SessionState) -> str | None | _Escape:
        v = result.verdict
        if v is not None:
            if v.kind is VerdictKind.REPAIR and v.layer is not None:
                return self.back_edges.get(v.layer, ESCAPE)
            if v.kind is VerdictKind.ESCALATE:
                return "user"
        nxt = self.forward.get((node, result.branch))
        for rw in self.rewrites:
            nxt = rw.apply(nxt, state)
        return nxt


@dataclass(frozen=True)
class Graph:
    """그래프의 정체성: 정점 집합(nodes) + 라우팅 정책(edges) + 진입 노드(entry).
    CompiledGraph 가 이걸 노드로 감싸 서브그래프로 만든다 (이후 태스크)."""
    nodes: NodeRegistry
    edges: EdgeTable
    entry: str

    def compile(self, *, name: str, fork: Fork, merge: Merge, exit_branch: "ExitBranch | None" = None, phase=None) -> "CompiledGraph":
        return CompiledGraph(self, name=name, fork=fork, merge=merge, exit_branch=exit_branch, phase=phase)


class _Merge:
    """CompiledGraph 의 출력. 바깥 Driver 의 `state = output.apply_to(state)` 한 줄이
    merge 를 수행한다 (apply_to 규약을 그대로 따른다)."""
    __slots__ = ("_merge", "_child")
    def __init__(self, merge, child):
        self._merge, self._child = merge, child
    def apply_to(self, parent):
        return self._merge(parent, self._child)


class CompiledGraph:
    """겉은 Node(name+run), 속은 그래프. fork 로 자식 스코프 진입, 안쪽 Driver 완주,
    merge 로 결과만 부모에 반영. 안에서 해결 못 한 verdict 는 바깥으로 bubble.
    exit_branch(child)->str|None 로 정상 종료 시 바깥 분기를 실을 수 있다."""

    def __init__(self, graph: "Graph", *, name: str, fork: Fork, merge: Merge, exit_branch: "ExitBranch | None" = None, phase=None):
        self.name = name
        self._graph = graph
        self._fork = fork
        self._merge = merge
        self._exit_branch = exit_branch
        self.phase = phase   # Driver reads node.phase when advancing the cursor

    async def run(self, ctx: NodeContext) -> NodeResult:
        from poor_code.domain.harness.driver import Driver   # lazy: avoid import cycle
        driver = Driver(self._graph.nodes, self._graph.edges.route)
        child = await driver.run(self._fork(ctx.state), ctx.cancel, sink=ctx.sink)
        if driver.last_escape is not None:
            return NodeResult(verdict=driver.last_escape)   # bubble unresolved verdict
        if child.pending_query is not None:
            # inner node suspended for user input → bubble the query outward. NOTE: on
            # resume the outer Driver re-enters this node and fork() restarts the subgraph
            # from its entry (subgraphs are atomic per design §4.7); shared-scope forks see
            # the user's answer in parent state, so the re-run is consistent.
            return NodeResult(query=child.pending_query)
        branch = self._exit_branch(child) if self._exit_branch is not None else None
        return NodeResult(output=_Merge(self._merge, child), branch=branch)
