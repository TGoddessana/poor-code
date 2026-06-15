# src/poor_code/domain/session/artifacts.py
"""Open data-plane artifact registry + generic (de)serialization. A registered artifact
is a STABLE string NAME <-> class mapping (deliberately NOT type.__name__, which is
refactor/collision fragile) plus a self-describing JSON conversion. This lets store.py
persist SessionState's open _data map generically (the 'extensions' section) without
per-type converter code — the serialization analogue of the open data plane."""
from __future__ import annotations

from typing import Any

_NAME_TO_CLASS: dict[str, type] = {}
_CLASS_TO_NAME: dict[type, str] = {}


def register_artifact(name: str, cls: type) -> None:
    """Register a stable name<->class pair. Idempotent for the same pair; raises if the
    name is already bound to a different class or the class to a different name (catches
    accidental clobber)."""
    existing = _NAME_TO_CLASS.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(f"artifact name {name!r} already registered to {existing!r}")
    prev = _CLASS_TO_NAME.get(cls)
    if prev is not None and prev != name:
        raise ValueError(f"class {cls!r} already registered under name {prev!r}")
    _NAME_TO_CLASS[name] = cls
    _CLASS_TO_NAME[cls] = name


def artifact_name(cls: type) -> str | None:
    return _CLASS_TO_NAME.get(cls)


def artifact_class(name: str) -> type | None:
    return _NAME_TO_CLASS.get(name)


def dump_artifact(value: Any) -> dict:
    """Serialize an artifact to a JSON-able dict via self-description: a pydantic
    BaseModel via model_dump(mode='json'); otherwise a to_json_dict() method."""
    md = getattr(value, "model_dump", None)
    if callable(md):
        return md(mode="json")
    tj = getattr(value, "to_json_dict", None)
    if callable(tj):
        return tj()
    raise TypeError(
        f"artifact {type(value)!r} is not serializable: define to_json_dict() "
        f"(or use a pydantic BaseModel)"
    )


def load_artifact(cls: type, payload: dict) -> Any:
    """Inverse of dump_artifact: pydantic via model_validate; else from_json_dict()."""
    mv = getattr(cls, "model_validate", None)
    if callable(mv):
        return mv(payload)
    fj = getattr(cls, "from_json_dict", None)
    if callable(fj):
        return fj(payload)
    raise TypeError(
        f"artifact {cls!r} is not deserializable: define from_json_dict() "
        f"(or use a pydantic BaseModel)"
    )
