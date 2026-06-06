"""Graph — (nodes + edges + entry) 의 1급 객체. EdgeTable 은 그래프별 토폴로지.
전역 route() 를 대체하되, 진입 그래프에선 동일 동작을 보존한다 (다음 태스크에서 배선)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from poor_code.domain.harness.node import NodeResult
from poor_code.domain.harness.registry import NodeRegistry
from poor_code.domain.session.models import Layer, SessionState, VerdictKind


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
