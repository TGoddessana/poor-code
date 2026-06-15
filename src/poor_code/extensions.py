"""Public extension surface for poor-code. Import from here to build custom nodes,
completions, artifacts, and subgraphs without reaching into internal modules:

    from poor_code.extensions import AgentNode, StructuredCompletion, register_artifact

This facade is deliberately NOT re-exported from the top-level `poor_code` package, so a
bare `import poor_code` does not pull in the graph runtime. Import this module explicitly
when you are extending the harness."""
from __future__ import annotations

from poor_code.domain.harness import (
    AgentNode,
    CompiledGraph,
    Completion,
    EdgeTable,
    Graph,
    Node,
    NodeContext,
    NodeRegistry,
    NodeResult,
    StructuredCompletion,
)
from poor_code.domain.session import (
    MissingInput,
    SessionState,
    artifact_class,
    artifact_name,
    register_artifact,
)

__all__ = [
    "AgentNode",
    "Completion",
    "StructuredCompletion",
    "Node",
    "NodeContext",
    "NodeResult",
    "Graph",
    "EdgeTable",
    "CompiledGraph",
    "NodeRegistry",
    "SessionState",
    "MissingInput",
    "register_artifact",
    "artifact_name",
    "artifact_class",
]
