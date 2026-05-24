from dataclasses import FrozenInstanceError

import pytest

from poor_code.slash.base import Arg, ArgKind, ParsedArgs, usage_hint


def test_arg_is_frozen():
    a = Arg(name="name", kind=ArgKind.TOKEN)
    with pytest.raises(FrozenInstanceError):
        a.name = "other"  # type: ignore[misc]


def test_arg_default_not_optional():
    assert Arg(name="x", kind=ArgKind.TOKEN).optional is False


def test_parsed_args_holds_values_and_raw():
    p = ParsedArgs(values={"name": "foo"}, raw="foo bar")
    assert p.values == {"name": "foo"}
    assert p.raw == "foo bar"


class _FakeCmd:
    name = "skill"
    description = "Run a skill"
    args = (Arg("name", ArgKind.TOKEN), Arg("prompt", ArgKind.REST, optional=True))
    def execute(self, ctx, parsed): pass


class _NoArgCmd:
    name = "login"
    description = "Sign in"
    args: tuple = ()
    def execute(self, ctx, parsed): pass


def test_usage_hint_no_args():
    assert usage_hint(_NoArgCmd()) == "/login"


def test_usage_hint_required_and_optional():
    assert usage_hint(_FakeCmd()) == "/skill <name> [prompt]"
