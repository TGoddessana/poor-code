# src/poor_code/domain/harness/contracts.py
"""Best-effort node I/O contract check. Every data TYPE a node `requires` should be
`produced` by some node in the same registry. This is a COVERAGE check (does a producer
exist at all), not an ordering check — and it WARNS, never fails: rewrites (e.g. FULL_AUTO
skipping the interviewer) and seeded inputs (the request) can satisfy a requirement the
static view cannot see. Surfaced at graph-build time so a misconfigured graph is caught
before a run rather than as a deep NoneType crash mid-flight."""
from __future__ import annotations

from poor_code.domain.harness.registry import NodeRegistry


def contract_warnings(registry: NodeRegistry) -> list[str]:
    """Return one human-readable warning per (node, required-type) whose type is not in
    the union of all nodes' `produces`. Reads declarations via getattr so any Node shape
    (AgentNode, GateNode, CompiledGraph, plain leaf) participates; undeclared → ()."""
    produced: set[type] = set()
    for name in registry.names():
        node = registry.get(name)
        produced.update(getattr(node, "produces", ()) or ())
    out: list[str] = []
    for name in registry.names():
        node = registry.get(name)
        for t in getattr(node, "requires", ()) or ():
            if t not in produced:
                tname = getattr(t, "__name__", str(t))
                out.append(
                    f"node {name!r} requires {tname} but no registered node produces it"
                )
    return out
