"""JSON-schema helpers for the schemas we hand to the LLM as tool `parameters`.

Pydantic emits nested models as ``$ref`` pointers into a ``$defs`` table. Some
models served over Ollama Cloud (observed: minimax-m3) mishandle a ``$ref``-
indirected *array* field: instead of a bare JSON array they emit the array
wrapped in an object, ``{"item": [...]}`` — which then fails schema validation
("options: Input should be a valid array"). Measured on minimax-m3:cloud with
the interviewer's output schema: 0/8 valid while the schema carried ``$ref``/
``$defs``; 7/8 valid once the refs were inlined (the one miss was an unrelated
HTTP 500). Flat schemas (no ``$ref``) were 8/8 regardless of streaming.

So before sending a tool schema we inline all ``$ref``s into a self-contained
tree. Validation still uses the real pydantic model — this only changes the
schema the model is *shown*, never what we accept.
"""
from __future__ import annotations

from typing import Any


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` with every ``$ref`` resolved against its own ``$defs``
    and the ``$defs`` table dropped, yielding a self-contained schema.

    Sibling keys alongside a ``$ref`` (rare, but legal) are preserved and layered
    over the resolved target. Recursive models are guarded against: a ``$ref`` that
    points back into a definition already being expanded is left unresolved rather
    than looping forever (none of the current output models are recursive)."""
    defs = schema.get("$defs", {})

    def resolve(node: Any, expanding: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref is not None:
                name = ref.rsplit("/", 1)[-1]
                target: dict[str, Any]
                if name in expanding or name not in defs:
                    target = {}  # cycle or dangling ref → leave a permissive object
                else:
                    target = resolve(defs[name], (*expanding, name))
                extra = {k: resolve(v, expanding) for k, v in node.items() if k != "$ref"}
                return {**target, **extra}
            return {k: resolve(v, expanding) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v, expanding) for v in node]
        return node

    return resolve({k: v for k, v in schema.items() if k != "$defs"}, ())
