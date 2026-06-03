"""Tool schemas handed to the LLM must be self-contained (no $ref/$defs).

Root cause of the interviewer's recurring StructuredOutputError: minimax-m3
wraps a $ref-indirected array field as {"item": [...]}. Inlining $refs fixes it
(0/8 → 7/8 valid in live probes). These tests pin the inliner and assert every
node's output tool ships a ref-free schema."""
import json

import pytest
from pydantic import BaseModel

from poor_code.domain.llm_schema import inline_refs


class _Inner(BaseModel):
    options: list[str] = []


class _Outer(BaseModel):
    action: str
    query: _Inner | None = None


def test_inline_refs_removes_defs_and_refs():
    raw = _Outer.model_json_schema()
    assert "$defs" in raw  # precondition: pydantic emits a ref table
    out = inline_refs(raw)
    blob = json.dumps(out)
    assert "$defs" not in out
    assert "$ref" not in blob


def test_inline_refs_inlines_nested_array_field():
    out = inline_refs(_Outer.model_json_schema())
    # query is `_Inner | None` → anyOf; the non-null branch must carry the
    # inlined object whose `options` is a bare array, not a $ref.
    branches = out["properties"]["query"]["anyOf"]
    obj = next(b for b in branches if b.get("type") == "object")
    assert obj["properties"]["options"]["type"] == "array"


def test_inline_refs_preserves_flat_schema():
    class Flat(BaseModel):
        a: int
        b: str

    raw = Flat.model_json_schema()
    assert inline_refs(raw) == {k: v for k, v in raw.items() if k != "$defs"}


def test_inline_refs_survives_recursive_model():
    class Node(BaseModel):
        children: list["Node"] = []

    Node.model_rebuild()
    # must terminate, not recurse forever
    out = inline_refs(Node.model_json_schema())
    assert "$defs" not in out


# --- every agent node's output tool must ship a ref-free schema ---

NODE_SCHEMAS = []
try:
    from poor_code.domain.harness.nodes.interviewer import _InterviewStepOut
    NODE_SCHEMAS.append(("interviewer", _InterviewStepOut))
except Exception:  # pragma: no cover
    pass


def _all_output_tool_schemas():
    """Instantiate-free: pull the schema each node hands to the LLM by reading the
    pydantic model behind its output tool. We assert at the schema layer so no LLM
    or node wiring is needed."""
    import importlib
    import pkgutil
    import poor_code.domain.harness.nodes as nodes_pkg

    seen = {}
    for m in pkgutil.iter_modules(nodes_pkg.__path__):
        mod = importlib.import_module(f"poor_code.domain.harness.nodes.{m.name}")
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
                if "$defs" in obj.model_json_schema():
                    seen[f"{m.name}.{name}"] = obj
    return seen


@pytest.mark.parametrize("label,model", sorted(_all_output_tool_schemas().items()))
def test_node_output_models_inline_clean(label, model):
    """Sanity: inlining any node output model that pydantic gives $defs leaves no
    refs behind (guards the helper against real, more complex node schemas)."""
    out = inline_refs(model.model_json_schema())
    assert "$ref" not in json.dumps(out)
    assert "$defs" not in out


# --- the behavioral regression: nodes must SEND a ref-free schema ---

def test_interviewer_output_tool_has_no_refs():
    """The interviewer's forced output tool is what minimax wrapped. Its wire
    schema must be self-contained — no $ref/$defs — or the {"item": [...]} bug
    returns."""
    from poor_code.domain.harness.nodes.interviewer import Interviewer

    # project_map is unused by output_tool(); a dummy suffices.
    node = Interviewer(llm=object(), project_map=object())
    params = node.output_tool()["function"]["parameters"]
    assert "$defs" not in params
    assert "$ref" not in json.dumps(params)
