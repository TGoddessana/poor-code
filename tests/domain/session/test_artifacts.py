from dataclasses import dataclass

import pytest

from poor_code.domain.session.artifacts import (
    register_artifact, artifact_name, artifact_class, dump_artifact, load_artifact,
)


@dataclass(frozen=True)
class _Widget:
    n: int

    def to_json_dict(self) -> dict:
        return {"n": self.n}

    @classmethod
    def from_json_dict(cls, d: dict) -> "_Widget":
        return cls(n=d["n"])


def test_register_and_bidirectional_lookup():
    register_artifact("widget", _Widget)
    assert artifact_class("widget") is _Widget
    assert artifact_name(_Widget) == "widget"


def test_register_idempotent_same_pair():
    register_artifact("widget", _Widget)
    register_artifact("widget", _Widget)
    assert artifact_class("widget") is _Widget


def test_register_conflicting_name_raises():
    @dataclass
    class _Other:
        pass
    register_artifact("widget", _Widget)
    with pytest.raises(ValueError):
        register_artifact("widget", _Other)


def test_dump_load_roundtrip_dataclass_protocol():
    register_artifact("widget", _Widget)
    payload = dump_artifact(_Widget(7))
    assert payload == {"n": 7}
    assert load_artifact(_Widget, payload) == _Widget(7)


def test_dump_load_pydantic_fallback():
    from pydantic import BaseModel

    class _PModel(BaseModel):
        x: str

    register_artifact("pmodel", _PModel)
    payload = dump_artifact(_PModel(x="hi"))
    assert payload == {"x": "hi"}
    assert load_artifact(_PModel, payload) == _PModel(x="hi")


def test_unknown_name_returns_none():
    assert artifact_class("does-not-exist") is None


def test_non_serializable_artifact_raises():
    class _Bare:
        pass
    with pytest.raises(TypeError):
        dump_artifact(_Bare())
