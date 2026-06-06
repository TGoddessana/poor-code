from datetime import UTC, datetime
from pathlib import Path


def test_build_default_graph_wraps_registry_and_edges():
    # build_default_graph returns a Graph with entry 'router' and the DEFAULT_EDGES table.
    from poor_code.domain.harness import build_default_graph
    from poor_code.domain.harness.route import DEFAULT_EDGES
    from poor_code.domain.project_map.models import ProjectMap

    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    g = build_default_graph(llm=object(), project_map=pm)
    assert g.entry == "router"
    assert g.edges is DEFAULT_EDGES
    assert g.nodes.get("router") is not None
