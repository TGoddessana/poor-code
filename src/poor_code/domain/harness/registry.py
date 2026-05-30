# src/poor_code/domain/harness/registry.py
"""NodeRegistry — name → Node. The graph's vertex set."""
from __future__ import annotations

from poor_code.domain.harness.node import Node


class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def register(self, node: Node) -> None:
        self._nodes[node.name] = node

    def get(self, name: str) -> Node | None:
        return self._nodes.get(name)
