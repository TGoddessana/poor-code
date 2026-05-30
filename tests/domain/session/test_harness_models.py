from poor_code.domain.session.models import (
    Request, RequestKind, CodeRef, CodeContext,
    Cursor, Phase, Transition, TriggerKind,
    Verdict, VerdictKind, Layer,
)


def test_request_kind_roundtrip():
    r = Request(raw_text="add oauth login", kind=RequestKind.ENGINEERING)
    assert r.kind is RequestKind.ENGINEERING
    assert r.raw_text == "add oauth login"


def test_code_context_holds_coderefs():
    cc = CodeContext(
        candidates=(CodeRef(file="src/a.py", symbol="login", lineno=10),),
        confusers=(CodeRef(file="src/b.py"),),
        related_tests=(CodeRef(file="tests/test_a.py"),),
    )
    assert cc.candidates[0].symbol == "login"
    assert cc.confusers[0].symbol is None  # whole-file ref


def test_verdict_repair_carries_layer():
    v = Verdict(kind=VerdictKind.REPAIR, layer=Layer.PLAN, hint="missing task")
    assert v.kind is VerdictKind.REPAIR and v.layer is Layer.PLAN


def test_cursor_and_transition_are_frozen():
    import dataclasses
    cur = Cursor(phase=Phase.LOCATING, current_node="locator")
    tr = Transition(from_node="router", to_node="locator",
                    trigger=TriggerKind.FORWARD, reason="engineering", ts_iso="2026-05-31T00:00:00+00:00")
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        cur.current_node = "x"  # type: ignore[misc]
    assert tr.to_node == "locator"
