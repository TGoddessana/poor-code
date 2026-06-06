"""FM2: deterministic coercion of weak-model structured output.

Ollama Cloud has no constrained decoding, so a weak model often emits a list field
as a singular-key object — e.g. `"steps": {"step": [...]}` instead of `[...]` — which
is a pure ValidationError that used to kill the run. We repair the SHAPE
deterministically before validation (transport normalization, not schema relaxation:
the result is still schema-validated)."""
from typing import Optional

import pytest
from pydantic import BaseModel

from poor_code.domain.harness.node import (
    StructuredOutputError, coerce_to_schema, validate_output,
)


class _Item(BaseModel):
    k: str = ""


class _Box(BaseModel):
    items: list[_Item] = []
    tags: list[str] = []
    note: str = ""


class _OptBox(BaseModel):
    items: Optional[list[_Item]] = None
    tags: Optional[list[str]] = None


def test_coerce_preserves_none_for_optional_list():
    # None is valid for Optional[list[...]]; coercion must NOT wrap it as [None].
    out = coerce_to_schema({"items": None, "tags": None}, _OptBox)
    assert out["items"] is None
    assert out["tags"] is None


def test_validate_output_accepts_optional_list_as_none():
    box = validate_output(_OptBox, '{"items": null, "tags": null}', node="t")
    assert box.items is None and box.tags is None


def test_coerce_unwraps_singular_key_object_into_list():
    data = {"items": {"item": [{"k": "a"}, {"k": "b"}]}}
    out = coerce_to_schema(data, _Box)
    assert out["items"] == [{"k": "a"}, {"k": "b"}]


def test_coerce_wraps_single_object_into_list():
    data = {"items": {"k": "a"}}  # one object where a list is expected
    out = coerce_to_schema(data, _Box)
    assert out["items"] == [{"k": "a"}]


def test_coerce_wraps_scalar_into_str_list():
    assert coerce_to_schema({"tags": "x"}, _Box)["tags"] == ["x"]


def test_coerce_leaves_correct_shapes_untouched():
    data = {"items": [{"k": "a"}], "tags": ["x"], "note": "hi"}
    assert coerce_to_schema(data, _Box) == data


def test_coerce_does_not_touch_scalar_fields():
    # a string field that happens to be a dict is left for validation to reject
    data = {"note": "ok"}
    assert coerce_to_schema(data, _Box)["note"] == "ok"


def test_validate_output_accepts_singular_wrapped_list():
    raw = '{"items": {"item": [{"k": "a"}]}}'
    box = validate_output(_Box, raw, node="t")
    assert box.items[0].k == "a"


def test_validate_output_raises_structured_error_on_bad_json():
    with pytest.raises(StructuredOutputError):
        validate_output(_Box, "not json at all", node="t")


def test_validate_output_raises_structured_error_on_schema_violation():
    # items[].k must be str; an int that can't coerce -> StructuredOutputError, not raw
    with pytest.raises(StructuredOutputError):
        validate_output(_Box, '{"items": [{"k": {"nested": 1}}]}', node="t")
